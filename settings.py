# -*- coding: utf-8 -*-

import os
if os.environ.get('HTTP_HOST'):
    url = os.environ['HTTP_HOST']
else:
    url = os.environ['SERVER_NAME']

if url.endswith(':8080'):
    DEBUG = True
    TEMPLATE_DEBUG = DEBUG
else:
    DEBUG = False
    TEMPLATE_DEBUG = False

NUM_MAIN = 15
UTC_OFFSET = +8