import xadmin
from models import *

class CourseUserTaskAdmin(object):
    pass

# Register your models here.
xadmin.site.register(CourseUserTask, CourseUserTaskAdmin)
