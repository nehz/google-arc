# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import multiprocessing
import time
import traceback

import ninja_generator

from util import concurrent


# Represents an individual task to run on |ninja_generator_runner|.
# Given |generator_context| is passed around the primary task and tasks
# requested by the primary task.  For each result of the task,
# generator_context.make_result is called to make the result to be returned to
# the caller of |run_in_parallel|.
#
# |generator_task| is a function to run as the body of the task, or a tuple
# that has the function as the first element and its arguments as the rest.
#
# Both |generator_context| and |generator_task| must be picklable.
class GeneratorTask:
  def __init__(self, generator_context, generator_task):
    self.context = generator_context
    if isinstance(generator_task, tuple):
      self.function = generator_task[0]
      self.args = generator_task[1:]
    else:
      self.function = generator_task
      self.args = []


# This is used to request back from a sub process to the parent process
# to request to run tasks in parallel. Available only under _run_task.
__request_task_list = None


def request_run_in_parallel(*task_list):
  """Requests back to the parent process to run task_list in parallel."""
  # Just append to the list. The tasks will be returned to the parent process,
  # and the parent process will handle them. See also _run_task and
  # run_in_parallel.
  __request_task_list.extend(task_list)


def _run_task(generator_task):
  """Run a generate ninja task synchronously.

  This is a helper to run generate_ninja() functions in multiprocessing, and
  will be called multiple times in each sub process.
  To run this function from the multiprocess.Pool, we need to make it a
  module top-level function.

  At the beginning of the task, NinjaGenerator._ninja_list and
  __request_task_list must be empty. In NinjaGenerator's ctor, the instance
  will be stored in the NinjaGenerator._ninja_list, and this function returns
  it (to parent process) as a result.
  Instead of creating NinjaGenerator, generate_ninja() and
  generate_test_ninja() can call request_run_in_parallel(). Then, this function
  returns tasks to the parent process, and they'll be run in parallel.
  """
  try:
    # Make sure both lists are empty.
    assert not ninja_generator.NinjaGenerator._ninja_list
    global __request_task_list
    assert not __request_task_list
    __request_task_list = []

    start_time = time.time()
    context = generator_task.context
    function = generator_task.function
    args = generator_task.args
    context.set_up()
    function(*args)
    context.tear_down()
    elapsed_time = time.time() - start_time
    if elapsed_time > 1:
      logging.info('Slow task: %s.%s %0.3fs',
                   function.__module__, function.__name__, elapsed_time)

    # Extract the result from global variables.
    ninja_list = ninja_generator.NinjaGenerator.consume_ninjas()
    task_list = [GeneratorTask(context, requested_task)
                 for requested_task in __request_task_list]

    result = context.make_result(ninja_list) if ninja_list else None

    # At the moment, it is prohibited 1) to return NinjaGenerator and
    # 2) to request to run ninja generators back to the parent process, at the
    # same time.
    assert (not result or not task_list)
    return (result, task_list)
  except BaseException:
    if multiprocessing.current_process().name == 'MainProcess':
      # Just raise the exception up the single process, single thread
      # stack in the simple -j1 case.
      raise
    # Consume the partially generated list of ninja files to avoid
    # re-entrance assertions in this function.
    ninja_generator.NinjaGenerator.consume_ninjas()
    # multiprocessing.Pool will discard the stack trace information.
    # So here, we format the message and raise another Exception with it.
    message = traceback.format_exc()
    # Print the exception here because we cannot re-raise all exceptions back to
    # the parent process because they cannot be unpickled correctly. See:
    # http://bugs.python.org/issue9400
    print message
    raise Exception('subprocess failure, see console output above')
  finally:
    __request_task_list = None


def run_in_parallel(task_list, maximum_jobs):
  """Runs task_list in parallel on multiprocess.

  Returns a list of NinjaGenerator created in subprocesses.
  If |maximum_jobs| is set to 0, this function runs the ninja generation
  synchronously in process.
  """
  if maximum_jobs == 0:
    executor = concurrent.SynchronousExecutor()
  else:
    executor = concurrent.ProcessPoolExecutor(max_workers=maximum_jobs)

  result_list = []
  with executor:
    try:
      # Submit initial tasks.
      not_done = {executor.submit(_run_task, generator_task)
                  for generator_task in task_list}
      while not_done:
        # Wait any task is completed.
        done, not_done = concurrent.wait(
            not_done, return_when=concurrent.FIRST_COMPLETED)

        for completed_future in done:
          if completed_future.exception():
            # An exception is raised in a task. Cancel remaining tasks and
            # re-raise the exception.
            for future in not_done:
              future.cancel()
            not_done = []
            raise completed_future.exception()

          # The task is completed successfully. Process the result.
          result, request_task_list = completed_future.result()
          if request_task_list:
            # If sub tasks are requested, submit them.
            assert not result
            not_done.update(
                executor.submit(_run_task, generator_task)
                for generator_task in request_task_list)
            continue

          if result:
            result_list.append(result)
    except:
      # An exception is raised. Terminate the running workers.
      if isinstance(executor, concurrent.ProcessPoolExecutor):
        executor.terminate()
      raise

  return result_list
