# -*- coding: utf-8 -*-
from django.shortcuts import render
from django.http import HttpResponse,HttpResponsePermanentRedirect,HttpResponseRedirect
from django.db.models import Sum
from django.conf import settings
from django.core.paginator import Paginator
from django.core.paginator import PageNotAnInteger
from django.core.paginator import EmptyPage
from django.contrib.auth.models import Group
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from django.db.models import Q
from mz_common.models import *
from mz_user.forms import *
from mz_course.models import *
from mz_lps.models import *
from utils.tool import upload_generation_dir
from utils import xinge
import json, logging, os, uuid,urllib2,urllib
from itertools import chain
# from mz_async.models import *
from mz_user.models import *
from mz_common.views import *
import time
from models import CourseUserTask


logger = logging.getLogger('mz_lps.views')


# global value setting
HOURS_PER_VIDEO = 1
HOURS_PER_PROJ = 5
DEFAULT_HOURS_PER_WEEK = 15

# 判读是否有重修课程
def __has_rebuild():
    return False

# 判断是否存在变更的课程（如新增章节或项目制作）
def __has_updated_courses():
    return False

# 处理变更课程
def __handle_updated_courses():
    pass

# 判断职业课程是否已结束
def __is_end_careercourse():
    return False

# 比较两个课程间的先后顺序
def __handle_cmp(a, b):
    if a.stages.index > b.stages.index:
        return 1
    elif a.stages.index < b.stages.index:
        return -1
    else:
        if a.stages.id > b.stages.id:
            return 1
        elif a.stages.id < b.stages.id:
            return -1
        else:
            if a.index > b.index:
                return 1
            elif a.index < b.index:
                return -1
            else:
                return a.id >= b.id and 1 or -1

def plan_for_nextweek(user_id, class_id):
    if __is_end_careercourse():
        if __has_updated_courses():
            __handle_updated_courses()
            return None
    try:
        my_class = Class.objects.get(id=class_id)
    except:
        assert False

    try:
        user = UserProfile.objects.get(id=user_id)
    except:
        assert False

    career_course = my_class.career_course
    IS_FIRST_TASK = False
    learning_hours = 0
    learning_plans = {}
    next_course = None
    next_lesson = None
    start_type = None # 起始任务项类型： 'P' 或者 'V'

    # 获得上周任务表
    try:
        pre_course_user_task = CourseUserTask.objects.select_related().filter(user=user, user_class=my_class).order_by('-create_datetime')[0] #默认按建立时间从近到远返回结果集
    except: # 刚开始进入该职业课程
        pre_learning_hours = DEFAULT_HOURS_PER_WEEK
        IS_FIRST_TASK = True
    else:
        # 当前根据上周实际完成学时数，生成下周计划学时数，可据此小幅调整（由于不可切分项目制作缘故）
        # 获得上周实际完成学时数
        pre_learning_hours = pre_course_user_task.real_study_time


        # 获得上周最近任务项（可能是视频章节或项目制作）
        pre_task_content = json.loads(pre_course_user_task.relate_content)
        recent_course_proj = None
        recent_course_video = None
        recent_course = None
        recent_course_flag = None
        recent_lesson = None

        # 如果有额外完成项目制作任务
        if pre_task_content.has_key('EP'):
            course_id_set = pre_task_content['EP'].keys() # 上周额外完成的项目制作任务所属的课程ID集合
            try:
                course_set = Course.objects.select_related().filter(id__in=course_id_set)#.order_by('-index', '-id')
            except:
                assert False

            sorted_set = sorted(course_set, cmp=__handle_cmp, key=lambda e:e, reverse=True)
            recent_course_proj = sorted_set[0] #获得项目制作所属最近学习课程

        # 如果有额外完成视频章节任务
        if pre_task_content.has_key('EV'):
            course_id_set = pre_task_content['EV'].keys() # 上周额外完成的视频章节任务所属的课程ID集合
            try:
                course_set = Course.objects.select_related().filter(id__in=course_id_set)#.order_by('-index', '-id')
            except:
                assert False

            sorted_set = sorted(course_set, cmp=__handle_cmp, key=lambda e:e, reverse=True)
            recent_course_video = sorted_set[0] #获得视频章节所属最近学习课程
            lesson_id_set = pre_task_content['EV'][recent_course_video.id]
            try:
                lesson_set = Lesson.objects.select_related().filter(id__in=lesson_id_set).order_by('-index', '-id')
            except:
                assert False
            recent_lesson = lesson_set[0] # 获得最近学习视频章节

        # 没有额外完成任务
        if not pre_task_content.has_key('EP') and not pre_task_content.has_key('EV'):
            if pre_task_content.has_key('P'):
                course_id_set = pre_task_content['P'].keys() # 上周规定完成项目制作任务所属的课程ID集合
                try:
                    course_set = Course.objects.select_related().filter(id__in=course_id_set)#.order_by('-index', '-id')
                except:
                    assert False

                sorted_set = sorted(course_set, cmp=__handle_cmp, key=lambda e:e, reverse=True)
                recent_course_proj = sorted_set[0] #获得项目制作所属最近学习课程

            if pre_task_content.has_key('V'):
                course_id_set = pre_task_content['V'].keys() # 上周规定完成视频章节任务所属的课程ID集合

                try:
                    course_set = Course.objects.select_related().filter(id__in=course_id_set)#.order_by('-index', '-id')
                except:
                    assert False

                sorted_set = sorted(course_set, cmp=__handle_cmp, key=lambda e:e, reverse=True)

                recent_course_video = sorted_set[0] #获得视频章节所属最近学习课程
                recent_lesson_id = pre_task_content['V'][str(recent_course_video.id)][1]
                try:
                    recent_lesson = Lesson.objects.get(id=recent_lesson_id)
                except:
                    # 上周实际工作量为0
                    return None


        # 计算下一周任务的起始课程和对应视频章节或项目制作
        if recent_course_proj and recent_course_video:
            if recent_course_proj.index > recent_course_video.index or \
                    (recent_course_proj.index == recent_course_video.index and
                     recent_course_proj.id >= recent_course_video.id):
                recent_course_flag = 'P'
                recent_course = recent_course_proj
            else:
                recent_course_flag = 'V'
                recent_course = recent_course_video
        elif recent_course_proj: # 上周只有项目制作任务
            recent_course_flag = 'P'
            recent_course = recent_course_proj
        elif recent_course_video: # 上周只有视频章节任务
            recent_course_flag = 'V'
            recent_course = recent_course_video
        else:
            assert False

        if recent_course_flag is 'P':
            start_type = 'V'

            try:
                my_stage = recent_course.stages
                course_set = my_stage.getCourseSet().order_by('index', 'id')
            except:
                assert False

            i = 0
            for each_course in course_set:
                if each_course == recent_course:
                    break
                i += 1
            if i < course_set.count() - 1: # 本阶段下课程尚未结束
                next_course = course_set[i+1]
            else: # 本阶段下课程已经全部完成，进入下一阶段学习
                try:
                    stage_set = Stage.objects.select_related().filter(career_course=my_stage.career_course).order_by('index', 'id')
                except:
                    assert False

                i = 0
                for each_stage in stage_set:
                    if each_stage == my_stage:
                        break
                    i += 1
                if i < stage_set.count() - 1: # 职业课程还未结束
                    i += 1
                    course_set = stage_set[i].getCourseSet().order_by('index', 'id')
                    while not course_set: # 如果该阶段下课程为空
                        i += 1
                        if i >= stage_set.count():
                            # 在职业课程最后处理存在变更的课程（如新增章节或项目制作）
                            __handle_updated_courses()
                            print "职业课程学习完毕！"
                            return None
                        course_set = stage_set[i].getCourseSet().order_by('index', 'id')
                    next_course = course_set[0]
                else: # 职业课程已经全部完成
                    # 在职业课程最后处理存在变更的课程（如新增章节或项目制作）
                    __handle_updated_courses()
                    print "职业课程学习完毕！"
                    return None

        elif recent_course_flag is 'V':
            try:
                lesson_set = Lesson.objects.select_related().filter(course=recent_course).order_by('index', 'id')
            except:
                assert False

            i = 0
            for each_lesson in lesson_set:
                if each_lesson == recent_lesson:
                    break
                i += 1
            if i < lesson_set.count() - 1: # 同上
                next_lesson = lesson_set[i+1]
                next_course = recent_course
                start_type = 'V'
            else:
                next_course = recent_course
                start_type = 'P'

    # 生成下周计划任务
    if not IS_FIRST_TASK:
        # 第一轮课程查询 (处理拆分课程)
        if start_type == 'P':
            # 判断该课程下是否有项目制作
            if not Project.objects.filter(examine_type=5, relation_type=2, relation_id=next_course.id):
                pass
            else:
                tmp = {}
                tmp[next_course.id] = False
                try:
                    learning_plans['P'].update(tmp)
                except:
                    learning_plans['P'] = tmp
                learning_hours += HOURS_PER_PROJ
        elif start_type == 'V':
            if next_lesson: # 从对应课程下特定视频章节(非首章节)开始
                lesson_set = Lesson.objects.filter(course=next_course).order_by('index', 'id')

                tmp = {}
                tmp[next_course.id] = [0, 0, []]

                tmp_flag = False
                i = 0
                for each_lesson in lesson_set:
                    if each_lesson == next_lesson:
                        tmp_flag = True
                    if tmp_flag:
                        if learning_hours + HOURS_PER_VIDEO > pre_learning_hours:
                            break
                        tmp[next_course.id][2].append(lesson_set[i].id)
                        learning_hours += HOURS_PER_VIDEO
                    i += 1

                to_do_lessons = tmp[next_course.id][2]
                tmp[next_course.id][0] = len(to_do_lessons)
                tmp[next_course.id][1] = to_do_lessons[-1]
                try:
                    learning_plans['V'].update(tmp)
                except:
                    learning_plans['V'] = tmp

                if learning_hours >= pre_learning_hours:
                    # print learning_plans, learning_hours
                    # pdb.set_trace()
                    return [learning_plans, learning_hours]
                else:
                    # 判断课程下是否有项目制作
                    if not Project.objects.filter(examine_type=5, relation_type=2, relation_id=next_course.id):
                        pass
                    else:
                        tmp = {}
                        tmp[next_course.id] = False
                        try:
                            learning_plans['P'].update(tmp)
                        except:
                            learning_plans['P'] = tmp
                        learning_hours += HOURS_PER_PROJ

        if learning_hours >= pre_learning_hours:
            # print learning_plans, learning_hours
            # pdb.set_trace()
            return [learning_plans, learning_hours]


        # 处理重修课程
        #############
        #to do
        ##############
        if __has_rebuild():
            pass

        # 除video 首章节以外所有情况，都需要跳到下一课
        if not (start_type == 'V' and not next_lesson):
            course_set = Course.objects.filter(stages=next_course.stages).order_by('index', 'id')
            i = 0
            for each_course in course_set:
                if each_course == next_course:
                    break
                i += 1

            if i < course_set.count() - 1: # 同上
                next_course = course_set[i+1]
            else:
                stage_set = Stage.objects.filter(career_course=next_course.stages.career_course).order_by('index', 'id')
                i = 0
                for each_stage in stage_set:
                    if each_stage == next_course.stages:
                        break
                    i += 1

                if i < stage_set.count() - 1: # 同上
                    i += 1
                    course_set = stage_set[i].getCourseSet().order_by('index', 'id')
                    while not course_set: # 如果该阶段下课程为空
                        i += 1
                        if i >= stage_set.count():
                            # 在职业课程最后处理存在变更的课程（如新增章节或项目制作）
                            __handle_updated_courses()
                            print "职业课程学习完毕！"
                            return None
                        course_set = stage_set[i].getCourseSet().order_by('index', 'id')
                    next_course = course_set[0]
                else: # 同上
                    # 在职业课程最后处理存在变更的课程（如新增章节或项目制作）
                    __handle_updated_courses()
                    print "职业课程已学习完毕！"
                    # print learning_plans, learning_hours
                    # pdb.set_trace()
                    return [learning_plans, learning_hours]


    # 后续课程查询
    IS_ACTION = False
    try:
        stage_set = Stage.objects.select_related().filter(career_course=career_course).order_by('index', 'id')
    except:
        assert False

    for each_stage in stage_set:
        try:
            course_set = each_stage.getCourseSet().order_by('index', 'id')
        except:
            assert False
        for each_course in course_set:
            if IS_FIRST_TASK or each_course == next_course:
                IS_ACTION = True
                IS_FIRST_TASK = False
            if IS_ACTION:
                current_course = each_course
                lesson_set = Lesson.objects.filter(course=current_course).order_by('index', 'id')

                if not lesson_set: #如果课程下无视频章节，则跳过该课程
                    continue

                tmp = {}
                tmp[current_course.id] = [0, 0, []]

                for each_lesson in lesson_set:
                    if learning_hours + HOURS_PER_VIDEO > pre_learning_hours:
                        break
                    tmp[current_course.id][2].append(each_lesson.id)
                    learning_hours += HOURS_PER_VIDEO

                to_do_lessons = tmp[current_course.id][2]
                tmp[current_course.id][0] = len(to_do_lessons)
                tmp[current_course.id][1] = to_do_lessons[-1]
                try:
                    learning_plans['V'].update(tmp)
                except:
                    learning_plans['V'] = tmp
                if learning_hours >= pre_learning_hours:
                    # print learning_plans, learning_hours
                    # pdb.set_trace()
                    return [learning_plans, learning_hours]
                else:
                    tmp = {}
                    tmp[current_course.id] = False
                    try:
                        learning_plans['P'].update(tmp)
                    except:
                        learning_plans['P'] = tmp
                    learning_hours += HOURS_PER_PROJ

                if learning_hours >= pre_learning_hours:
                    # print learning_plans, learning_hours
                    # pdb.set_trace()
                    return [learning_plans, learning_hours]
    # print learning_plans, learning_hours
    # pdb.set_trace()
    return [learning_plans, learning_hours]

def update_study_point_score(student, study_point=None, score=None, examine=None, examine_record=None, teacher=None, course=None, rebuild_count=None, stage_id=-1):
    '''
    更新学力和测验分
    :param student: 学生对象
    :param study_point: 学力加分（可选项）
    :param score: 测验分加分（可选项）
    :param examine: 考核对象（可选项）
    :param examine_record: 考核记录对象（可选项）
    :param teacher: 老师对象（可选项）
    :param course: 课程（可选项）,更新非考核产生的学力和学分时候需传入
    :param rebuild_count: 第几次重修（可选项）
    :return:
    '''

    if course is None:
        cur_course = Course()
    else:
        cur_course = course
        # 根据考核对象类型找到相应对象
    # 章节
    if examine is not None and examine_record is not None:
        if examine.relation_type == 1:
            cur_lesson = Lesson.objects.filter(pk=examine.relation_id)
            if len(cur_lesson) > 0:
                cur_course = cur_lesson[0].course
        #课程
        elif examine.relation_type == 2:
            cur_course = Course.objects.filter(pk=examine.relation_id)
            if len(cur_course)  > 0:
                cur_course = cur_course[0]

        if rebuild_count is None:
            rebuild_count = get_rebuild_count(student, cur_course)

        # 更新考核记录学力
        if score is not None:
            examine_record.score = score  # 计算该试卷测验得分
            if teacher is not None:
                examine_record.teacher = teacher
        if study_point is not None:
            examine_record.study_point = study_point   # 学力
        examine_record.save()

        # 在coursescore中更新测验分
        check_course_score(student, cur_course) # 检查是否有course_score记录,没有则创建
        if examine.examine_type in(2,5) and score is not None:
            course_score = CourseScore.objects.filter(user=student,course=cur_course,rebuild_count=rebuild_count)
            if len(course_score):
                # 考试测验
                # 试卷类型测验分
                if examine.examine_type == 2:
                    # 随堂测验
                    if examine.relation_type == 1:
                        # 获取所有章节id列表
                        lesson_list = cur_course.lesson_set.all().values_list("id")
                        lesson_total_score = 0
                        # 获取所有章节对应的paper
                        paper_list = Paper.objects.filter(examine_type=2, relation_type=1, relation_id__in=lesson_list).values_list("id")
                        # 获取所有章节对应的paperrecord
                        paper_record_list = PaperRecord.objects.filter(Q(student=student),Q(paper__in=paper_list),Q(rebuild_count=rebuild_count),~Q(score=None))
                        # 计算随堂测验总分
                        for paper_record in paper_record_list:
                            lesson_total_score += (100 / len(paper_list)) * paper_record.accuracy
                        course_score[0].lesson_score = int(round(lesson_total_score))
                    # 课程总测验
                    elif examine.relation_type == 2:
                        course_score[0].course_score = score
                # 项目类型测验分
                elif examine.examine_type == 5:
                    course_score[0].project_score = score
                    # 检查测验分考核项是否已经完全考核
                if check_exam_is_complete(student, cur_course) == 1:
                    course_score[0].is_complete = True  # 所有测验完成状态
                    course_score[0].complete_date = datetime.now()  # 测验完成时间
                    career_course = cur_course.getStages(stage_id).career_course
                    # 如已完成所有考核项，则发送课程通过与否的站内消息
                    total_score = get_course_score(course_score[0], cur_course)
                    if total_score >= 60:
                        sys_send_message(0, student.id, 1, "恭喜您已通过<a href='/lps/learning/plan/"+str(career_course.id)+"/'>"+
                                                           str(cur_course.name)+"</a>课程，总获得测验分"+str(total_score)+
                                                           "分！<a href='/lps/learning/plan/"+str(career_course.id)+"/'>继续学习下一课</a>")
                    else:
                        sys_send_message(0, student.id, 1, "您的课程<a href='/lps/learning/plan/"+str(career_course.id)+"/?stage_id="+str(cur_course.getStages(stage_id).id)+"'>"+str(cur_course.name)+
                                                           "</a>挂科啦。不要灰心，<a href='/lps/learning/plan/"+str(career_course.id)+"/?stage_id="+str(cur_course.getStages(stage_id).id)+"'>去重修</a>")
                        # 继续检查是否完成该阶段的所有考核项
                    if check_stage_exam_is_complete(student, cur_course):
                        # 如果完成了所有考核项，则检查该课程对应职业课程的所有阶段和解锁信息
                        stage_list = Stage.objects.filter(career_course=cur_course.getStages(stage_id).career_course)
                        cur_stage_count = 0
                        for i,stage in enumerate(stage_list):
                            if stage == cur_course.getStages(stage_id):
                                cur_stage_count = i
                                break
                        if (cur_stage_count+1) < len(stage_list):
                            # 检查下一个阶段是否已经解锁
                            if UserUnlockStage.objects.filter(user=student, stage=stage_list[cur_stage_count+1]).count()>0:
                                # 已经解锁
                                msg = "恭喜您能努力坚持学完"+career_course.name+"的第"+str(cur_stage_count+1)+"阶段，赶快继续深造吧，你离梦想仅一步之遥了哦！<a href='/lps/learning/plan/"+str(career_course.id)+"/?stage_id="+str(stage_list[cur_stage_count+1].id)+"'>立即学习下一阶段</a>"
                            else:
                                # 还未解锁
                                msg = "恭喜您能努力坚持学完"+career_course.name+"的第"+str(cur_stage_count+1)+"阶段，赶快续费继续深造吧，你离梦想仅一步之遥了哦！<a href='/lps/learning/plan/"+str(career_course.id)+"/?stage_id="+str(stage_list[cur_stage_count+1].id)+"'>立即购买下一阶段</a>"
                        else:
                            msg = "恭喜您能努力坚持学完"+career_course.name+"所有课程，你还可以继续深造哦！<a href='/course/'>去选课程</a>"
                        sys_send_message(0, student.id, 1, msg)
                else:
                    # 如果是未完成所有考核项，但是测验分已经超过了60分，则可以判定课程通过，提前更新课程测验完成状态
                    if get_course_score(course_score[0], cur_course) >= 60:
                        course_score[0].is_complete = True  # 所有测验完成状态
                course_score[0].save()

    # 更新班级学力汇总信息
    if study_point > 0 and rebuild_count == 0:
        class_students = ClassStudents.objects.filter(user=student,student_class__career_course=cur_course.getStages(stage_id).career_course)
        if len(class_students)>0:
            class_students[0].study_point += study_point
            class_students[0].save()

calcing = False
def calc_study_point():
    try:
        global calcing
        if calcing:
            return
        calcing=True
        async_methods=AsyncMethod.objects.filter(is_calc = False) #.order_by("-priority","submit_datetime")
        print "aaa1"
        #time.sleep(60)
        if len(async_methods):
            am=async_methods[0]
            if am.calc_type==1:
                amdict=json.loads(am.methods)
                update_study_point_score(student=UserProfile.objects.get(pk=amdict["student"]),
                                         study_point=amdict["study_point"],
                                         score=amdict["score"],
                                         examine= None if amdict["examine"]<0 else Examine.objects.get(pk=amdict["examine"]),
                                         examine_record= None if amdict["examine_record"]<0 else ExamineRecord.objects.get(pk=amdict["examine_record"]),
                                         teacher= None if amdict["teacher"]<0 else UserProfile.objects.get(pk=amdict["teacher"]),
                                         course= None if amdict["course"]<0 else Course.objects.get(pk=amdict["course"]),
                                         rebuild_count=amdict["rebuild_count"])

            am.calc_datetime = datetime.now()
            am.is_calc=True
            am.save()

    except Exception as e:
        print e

    calcing=False

def plan_module(): # 时间到了，要生成下一个课程的计划
    ret=False
    return ret
def finish_module(): #定期判断，课程是否完成，进度情况
    ret=False
    return ret
