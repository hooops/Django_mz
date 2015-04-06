__author__ = 'iswing'
import django.dispatch
post_save = django.dispatch.Signal(providing_args=['obj'])
