# -*- coding: utf-8 -*-

import functools
import hashlib
import logging
import os
import uuid
import urllib
import datetime
import time
import string
from google.appengine.dist import use_library
use_library("django", "1.0")

from django.conf import settings
settings._target = None
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"

from django.template.defaultfilters import slugify
from django.utils import feedgenerator
from django.utils import simplejson

from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.db import djangoforms
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app
NUM_MAIN = getattr(settings, "NUM_MAIN", 10)
UTC_OFFSET = getattr(settings, "UTC_OFFSET", 0)

webapp.template.register_template_library("highlight")


class Snippet(db.Model):
    author = db.UserProperty()
    name = db.StringProperty(required=False)
    lang = db.StringProperty(required=False)
    published = db.DateTimeProperty(auto_now_add=True)
    content = db.TextProperty(required=True)

class SnippetForm(djangoforms.ModelForm):
    class Meta:
        model = Snippet
        exclude = ['author','created', 'modified', 'lang']

def admin(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        user = users.get_current_user()
        if not user:
            if self.request.method == "GET":
                return self.redirect(users.create_login_url(self.request.uri))
            return self.error(403)
        elif not users.is_current_user_admin():
            return self.error(403)
        else:
            return method(self, *args, **kwargs)
    return wrapper
class BaseRequestHandler(webapp.RequestHandler):
    def initialize(self, request, response):
        webapp.RequestHandler.initialize(self, request, response)
        if request.path.endswith("/") and not request.path == "/":
            redirect = request.path[:-1]
            if request.query_string:
                redirect += "?" + request.query_string
            return self.redirect(redirect, permanent=True)

    def head(self, *args, **kwargs):
        pass

    def raise_error(self, code):
        self.error(code)
        self.render("%i.html" % code)
    def get_main_page_snippets(self, num=NUM_MAIN):
        key = "snippets/main/%d" % num
        snippets = memcache.get(key)
        if not snippets:
            snippets = db.Query(Snippet).order("-published").fetch(limit=num)
            memcache.set(key, list(snippets))
        return snippets
    def get_snippet_from_id(self, id):
        key = "snippet/%s" % id
        snippet = memcache.get(key)
        if not snippet:
            snippet = Snippet.get_by_id(int(id))
            if snippet:
                memcache.set(key, snippet)
        return snippet
    def get_same_lang_snippets(self, lang):
        key = "snippets/lang/%s" % lang
        snippets = memcache.get(key)
        if not snippets:
            snippets = db.Query(Snippet).filter("lang =", lang).order("-published")
            memcache.set(key, list(snippets))
        return snippets
    def kill_snippets_cache(self, id=None, lang=None):
        memcache.delete("snippets/main/%d" % NUM_MAIN)
        if id:
            memcache.delete("snippet/%s" % id)
        if lang:
            memcache.delete("snippets/lang/%s" % lang)
    def get_integer_argument(self, name, default):
        try:
            return int(self.request.get(name, default))
        except (TypeError, ValueError):
            return default
    def snippet_link(self, snippet, query_args={}, absolute=False):
        url = "/snippet/" + str(snippet.key().id())
        if absolute:
            url = "http://" + self.request.host + url
        if query_args:
            url += "?" + urllib.urlencode(query_args)
        return url
    
    def render(self, template_file, extra_context={}):
        extra_context["request"] = self.request
        extra_context["admin"] = users.is_current_user_admin()
        extra_context.update(settings._target.__dict__)
        template_file = "templates/%s" % template_file
        path = os.path.join(os.path.dirname(__file__), template_file)
        self.response.out.write(template.render(path, extra_context))

class MainPageHandler(BaseRequestHandler):
    def get(self):
        offset = self.get_integer_argument("start", 0)
        if not offset:
            snippets = self.get_main_page_snippets()
        else:
            snippets = db.Query(Snippet).order("-published").fetch(limit=NUM_MAIN,
                offset=offset)
        if not snippets and offset > 0:
            return self.redirect("/")
        extra_context = {
            "snippets": snippets,
            "next": max(offset - NUM_MAIN, 0),
            "previous": offset + NUM_MAIN if len(snippets) == NUM_MAIN else None,
            "offset": offset,
        }
        self.render("homepage.html", extra_context)
class LangPageHandler(BaseRequestHandler):
    def get(self, lang):
        extra_context = {
            "snippets": self.get_same_lang_snippets(lang),
            "lang": lang,
        }
        self.render("lang.html", extra_context)

class DeleteSnippetHandler(BaseRequestHandler):
    @admin
    def post(self):
        id = self.request.get("key")
        try:
            snippet = Snippet.get_by_id(int(id))
            snippet.delete()
            self.kill_snippets_cache(id=id, lang=snippet.lang)
            data = {"success": True}
        except db.BadKeyError:
            data = {"success": False}
        json = simplejson.dumps(data)
        self.response.out.write(json)
class SnippetPageHandler(BaseRequestHandler):
    def head(self, id):
        snippet = self.get_snippet_from_id(id=id)
        if not snippet:
            self.error(404)

    def get(self, id):
        snippet = self.get_snippet_from_id(id=id)
        if not snippet:
            return self.raise_error(404)

        format = self.request.get('format')
        if format == 'raw':
            self.response.headers["Content-Type"] = "text/plain; charset=utf-8"

        extra_context = {
            "snippets": [snippet], # So we can use the same template for everything
            "snippet": snippet, # To easily pull out the title
        }
        self.render("view.html" if not format else "view_%s.html"%format, extra_context)

class NewSnippetHandler(BaseRequestHandler):
    @admin
    def get(self, key=None):
        extra_context = {}
        form = SnippetForm()
        if key:
            try:
                snippet = db.get(key)
                extra_context["snippet"] = snippet
                form = SnippetForm(instance=snippet)
            except db.BadKeyError:
                return self.redirect("/new")
        extra_context["form"] = form
        self.render("edit.html" if key else "new.html", extra_context)

    @admin
    def post(self, key=None):
        extra_context = {}
        form = SnippetForm(data=self.request.POST)
        if form.is_valid():
            if key:
                try:
                    snippet = db.get(key)
                    extra_context["snippet"] = snippet
                except db.BadKeyError:
                    return self.raise_error(404)
                snippet.name = self.request.get("name")
                snippet.lang = self.request.get("lang")
                snippet.content = self.request.get("content")
            else:
                snippet = Snippet(
                    author=users.get_current_user(),
                    content=self.request.get("content"),
                    name=self.request.get("name"),
                    lang=self.request.get("lang"),
                )
            if not key:
                snippet.published += datetime.timedelta(hours=UTC_OFFSET)
            snippet.put()
            self.kill_snippets_cache(id=snippet.key().id() if key else None,
                lang=snippet.lang)

            return self.redirect(self.snippet_link(snippet))
        extra_context["form"] = form
        self.render("edit.html" if key else "new.html", extra_context)

class LoginHandler(BaseRequestHandler):
    def get(self):
        try:
            self.referer = self.request.headers['referer']
        except:
            self.referer = "/"
        return self.redirect(users.create_login_url(self.referer))

class LogoutHandler(BaseRequestHandler):
    def get(self):
        try:
            self.referer = self.request.headers['referer']
        except:
            self.referer = "/"
        return self.redirect(users.create_logout_url(self.referer))
class NotFoundHandler(BaseRequestHandler):
    def head(self):
        self.error(404)

    def get(self):
        self.raise_error(404)

application = webapp.WSGIApplication([
    ("/", MainPageHandler),
    ("/delete/?", DeleteSnippetHandler),
    ("/edit/([\w-]+)/?", NewSnippetHandler),
    ("/snippet/([\w-]+)/?", SnippetPageHandler),
    ("/new/?", NewSnippetHandler),
    ("/lang/([\w-]+)/?", LangPageHandler),
    ("/login/?", LoginHandler),
    ("/logout/?", LogoutHandler),
    ("/.*", NotFoundHandler),
], debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
    main()