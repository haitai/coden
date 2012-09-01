#from django import template
from pygments.lexers import LEXERS, get_lexer_by_name
from pygments import highlight
from pygments.formatters import HtmlFormatter
#from django.template.defaultfilters import stringfilter
from google.appengine.ext import webapp
register = webapp.template.create_template_register()

#register = template.Library()
_lexer_names = reduce(lambda a,b: a + b[2], LEXERS.itervalues(), ())
_formatter = HtmlFormatter(cssclass='highlight')
#@register.filter
#@stringfilter
def pygments(value, lexer_name):
    if lexer_name and lexer_name in _lexer_names:
        lexer = get_lexer_by_name(lexer_name, stripnl=True, encoding='UTF-8')
        return highlight(value, lexer, _formatter)
    else:
        return value
register.filter(pygments)

def shortor(value):
    value_lines = value.split('\r\n')
    if len(value_lines) > 5:
        return ('\r\n').join(value_lines[:5])
    else:
        return value
register.filter(shortor)