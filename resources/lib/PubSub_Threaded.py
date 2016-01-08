#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#     Copyright (C) 2015 KenV99
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#

import Queue
import abc
import copy
import threading
import time

LOGLEVEL_CRITICAL = 50
LOGLEVEL_ERROR = 40
LOGLEVEL_WARNING = 30
LOGLEVEL_INFO = 20
LOGLEVEL_DEBUG = 10


class BaseLogger(object):
    __metaclass__ = abc.ABCMeta
    selfloglevel = LOGLEVEL_INFO

    @staticmethod
    def setLogLevel(loglevel):
        BaseLogger.selfloglevel = loglevel

    @staticmethod
    @abc.abstractmethod
    def log(*args):
        pass


class PrintLogger(BaseLogger):
    @staticmethod
    def log(loglevel=LOGLEVEL_INFO, msg='Log Event'):
        if loglevel >= BaseLogger.selfloglevel:
            print msg

class TaskReturn(object):
    def __init__(self, iserror=False, msg=''):
        self.iserror = iserror
        self.msg = msg
        self.taskId = None
        self.eventId = None


def DummyReturnHandler(*args, **kwargs):
    pass


class DummyLogger(BaseLogger):
    @staticmethod
    def log(*args):
        pass


class Topic(object):
    def __init__(self, topic, subtopic=None):
        self.topic = topic
        self.subtopic = subtopic

    def has_subtopic(self):
        if self.subtopic is None:
            return False
        else:
            return True

    def __eq__(self, other):
        assert isinstance(other, Topic)
        if other.has_subtopic():
            if self.has_subtopic():
                if other.topic == self.topic and other.subtopic == self.subtopic:
                    return True
                else:
                    return False
            else:  ## self has no subtopic
                return False
        else:
            if self.has_subtopic():
                if self.topic == other.topic:
                    return True
                else:
                    return False
            else:
                if self.topic == other.topic:
                    return True
                else:
                    return False

    def __repr__(self):
        if self.has_subtopic():
            return '%s:%s' % (self.topic, self.subtopic)
        else:
            return self.topic


class Message(object):
    def __init__(self, topic, **kwargs):
        self.topic = topic
        self.kwargs = kwargs


class Dispatcher(threading.Thread):
    def __init__(self, interval=0.1, sleepfxn=time.sleep):
        super(Dispatcher, self).__init__(name='Dispatcher')
        self._message_q = Queue.Queue()
        self._abort_evt = threading.Event()
        self._abort_evt.clear()
        self.subscribers = []
        self.running = False
        self.interval = interval
        self.sleepfxn = sleepfxn

    def addSubscriber(self, subscriber):
        assert isinstance(subscriber, Subscriber)
        wasrunning = False
        if self.running:
            self.abort()
            self.join()
            wasrunning = True
        self.subscribers.append(subscriber)
        if wasrunning:
            self.start()

    def q_message(self, message):
        self._message_q.put(copy.copy(message), block=False)

    def run(self):
        self.running = True
        while not self._abort_evt.is_set():
            while not self._message_q.empty():
                try:
                    msg = self._message_q.get_nowait()
                    assert isinstance(msg, Message)
                except Queue.Empty:
                    continue
                except AssertionError:
                    raise
                for s in self.subscribers:
                    if msg.topic in s.topics:
                        s.notify(msg)
            self.sleepfxn(self.interval)
        self.running = False

    def abort(self):
        if self.running:
            self._abort_evt.set()


class Publisher(object):
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    def publish(self, message):
        self.dispatcher.q_message(message)


class Task(threading.Thread):
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        super(Task, self).__init__()
        self.kwargs = {}
        self.userargs = []
        self.topic = None
        self.returnQ = Queue.Queue()

    def t_start(self, topic, *args, **kwargs):
        try:
            self.userargs = args
            self.kwargs = kwargs
            self.topic = topic
        except:
            pass
        self.start()

    @abc.abstractmethod
    def run(self):
        pass
        ret = TaskReturn()
        self.returnQ.put(ret)


class TaskManager(object):
    def __init__(self, task, maxrunning=1, refractory_period=None, max_runs=-1, **taskKwargs):
        self.task = task
        self.maxrunning = maxrunning
        self.refractory_period = refractory_period
        self.run_tasks = []
        self.most_recent_task_time = time.time()
        self.max_runs = max_runs
        self.run_count = 0
        self.taskKwargs = taskKwargs
        self.returnHandler = DummyReturnHandler

    def start(self, topic, **kwargs):
        taskReturn = TaskReturn(iserror=True)
        taskReturn.eventId = str(topic)
        taskReturn.taskId = ''
        if self.max_runs > 0:
            if self.run_count >= self.max_runs:
                taskReturn.msg = TaskManagerException_TaskCountExceeded.message
                self.returnHandler(taskReturn)
                return
        if self.maxrunning > 0:
            count = 0
            for i, t in enumerate(self.run_tasks):
                assert isinstance(t, threading.Thread)
                if t.is_alive():
                    count += 1
                else:
                    del t
                    del self.run_tasks[i]
            if count >= self.maxrunning:
                taskReturn.msg = TaskManagerException_TaskAlreadyRunning.message
                self.returnHandler(taskReturn)
                return
        if self.refractory_period > 0:
            tnow = time.time()
            if tnow - self.most_recent_task_time < self.refractory_period:
                taskReturn.msg = TaskManagerException_TaskInRefractoryPeriod.message
                self.returnHandler(taskReturn)
                return
            else:
                self.most_recent_task_time = tnow

        # Launch the task
        self.run_count += 1

        t = self.task()
        t.t_start(topic, self.taskKwargs, **kwargs)
        if self.maxrunning > 0:
            self.run_tasks.append(t)
        while t.returnQ.empty():
            pass
        taskReturn = t.returnQ.get_nowait()
        assert isinstance(taskReturn, TaskReturn)
        self.returnHandler(taskReturn)


class TaskManagerException_TaskCountExceeded(Exception):
    def __init__(self):
        super(TaskManagerException_TaskCountExceeded, self).__init__('Task not run because task count exceeded')


class TaskManagerException_TaskAlreadyRunning(Exception):
    def __init__(self):
        super(TaskManagerException_TaskAlreadyRunning, self).__init__('Task not run because task already running')


class TaskManagerException_TaskInRefractoryPeriod(Exception):
    def __init__(self):
        super(TaskManagerException_TaskInRefractoryPeriod, self).__init__(
                'Task not run because task is in refractory period')


class Subscriber(object):
    def __init__(self, logger=DummyLogger, loglevel=LOGLEVEL_INFO):
        self.topics = []
        self.taskmanagers = []
        self.logger = logger
        self.loglevel = loglevel

    def addTopic(self, topic):
        assert isinstance(topic, Topic)
        self.topics.append(topic)

    def addTaskManager(self, tm):
        assert isinstance(tm, TaskManager)
        self.taskmanagers.append(tm)

    def notify(self, message):
        for taskmanager in self.taskmanagers:
            try:
                self.logger.log(self.loglevel, 'Task starting for %s' % message.topic)
                taskmanager.start(message.topic, **message.kwargs)
            except TaskManagerException_TaskAlreadyRunning as e:
                self.logger.log(self.loglevel, '%s - %s' % (message.topic, e.message))
            except TaskManagerException_TaskInRefractoryPeriod as e:
                self.logger.log(self.loglevel, '%s - %s' % (message.topic, e.message))
            except TaskManagerException_TaskCountExceeded as e:
                self.logger.log(self.loglevel, '%s - %s' % (message.topic, e.message))
            except Exception as e:
                pass
            else:
                self.logger.log(self.loglevel, 'Task finalized for %s' % message.topic)
