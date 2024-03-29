#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright notice
# ----------------
#
# Copyright (C) 2013-2023 Daniel Jung
# Contact: proggy-contact@mailbox.org
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA.
#
"""pspace - a parameter space manager to create and maintain PBS jobs given the
combinations of predefined parameter values. Depends on the Portable Batch
System (PBS), thus is meant to be used on login servers of computer clusters
using PBS.

All commands expect one ore more configuration files as arguments.

Many commands can be interrupted by hitting CTRL-C on the keyboard.

For pspace to work, you need to create an executable script with the name
"pspace", which is calling the function *call()*, like this:

    >>> import sys, pspace
    >>> if __name__ == '__main__':
    >>>     sys.exit(pspace.call())
"""
__version__ = 'v0.1.0'

import getpass
import itertools
import numpy
import os
import subprocess
import sys
import time
import optparse
import progmon
import clitable


#=====================#
# Command definitions #
#=====================#


def create(*args):
    """Create datafiles, including the directory structure along the path.

    To create the datafiles, the command pattern CMD_FILE from the
    configuration file is used.

    In the typical usecase it is recommended to use the option --force to skip
    files that already exist and just "fill the gaps".

    Use the --param option to select only a certain parameter subspace."""

    # parse command line options
    op = optparse.OptionParser(usage='%prog create [options] CONFFILE ' +
                                     '[CONFFILE2 ...]',
                               version=__version__,
                               description=create.__doc__)
    op.add_option('-t', '--test', default=False, action='store_true',
                  help='test mode, show files that would have been created')
    op.add_option('-v', '--verbose', default=False, action='store_true',
                  help='be verbose, report skipped files')
    op.add_option('-q', '--quiet', default=False, action='store_true',
                  help='be quiet, do not even report created files')
    op.add_option('-p', '--param', default='',
                  help='filter parameters (define parameter subspace) in ' +
                       'the format "A=1,B=:5,C=3.7:8.2"')
    op.add_option('-f', '--force', default=False, action='store_true',
                  help='skip existing files, do not promt')
    op.add_option('-b', '--bar', default=False, action='store_true',
                  help='show progress bar')
    op.add_option('-o', '--overwrite', default=False, action='store_true',
                  help='overwrite parameter sets of existing files')
    if len(args) == 0:
        args = ['--help']
    opts, posargs = op.parse_args(args=list(args))
    if opts.bar:
        opts.quiet = True
    if opts.quiet:
        opts.verbose = False

    # remember shell's working directory
    cwd = os.getcwd()

    try:
        # cycle all given configuration files
        for conffile in conf_filenames(*posargs):
            conf = parse_conf(conffile)
            psets = filter_psets(compute_psets(conf), opts.param,
                                 conf['pnames'])
            datafiles = sorted(psets.keys())

            # go to working directory
            os.chdir(conf['WORKDIR'])

            # cycle datafiles for every parameter combination
            dirname = os.path.basename(os.path.dirname(conffile))
            with progmon.Bar(len(datafiles), text=dirname, verbose=opts.bar) \
                    as bar:
                for datafile in datafiles:
                    pset = psets[datafile]

                    #if not opts.overwrite:

                    ### WTFFFF!!!!!!!

                    # check if datafile already exists and check it
                    if os.path.isfile(datafile):
                        #if check_file(datafile):
                        if opts.force and not opts.overwrite or opts.test:
                            bar.step()
                            continue
                        elif not opts.overwrite:
                            bar.end()
                            print(f'pspace: create: cannot create file "{datafile}": File exists', file=sys.stderr)
                            sys.exit(1)

                    # elif not os.path.isfile(datafile) and
                    # os.path.exists(datafile):
                    if os.path.exists(datafile) \
                            and not os.path.isfile(datafile):
                        bar.end()
                        print(f'pspace: create: not a file: "{datafile}"', file=sys.stderr)
                        sys.exit(1)

                    #else:
                        #if not os.path.isfile(datafile) \
                                #and os.path.exists(datafile):
                        #bar.end()
                        #print(f'pspace: create: not a file: "{datafile}"', file=sys.stderr)
                        #sys.exit(1)

                    # create missing directories along the path
                    dirname = os.path.dirname(datafile)
                    if not opts.test:
                        if os.path.exists(dirname) \
                                and not os.path.isdir(dirname):
                            bar.end()
                            print(f'pspace: create: cannot create directory "{dirname}": File exists', file=sys.stderr)
                            sys.exit(1)
                        if not os.path.exists(dirname):
                            os.makedirs(dirname)

                    # create file using template
                    cmd = cmd_file(conf, pset)
                    if opts.test and not opts.quiet:
                        sys.stdout.write('pspace: create: would have ' +
                                         'created datafile "%s"\n' % datafile)
                        sys.stdout.flush()
                    else:
                        subprocess.call(cmd+' -O', shell=True)
                        if not opts.quiet:
                            sys.stdout.write('pspace: create: created ' +
                                             'datafile "%s"\n' % datafile)
                            sys.stdout.flush()

                    bar.step()

    except KeyboardInterrupt:
        if not opts.quiet:
            print('pspace: create: aborted by user')
    finally:
        # return to the shell's original working directory
        os.chdir(cwd)


def submit(*args):
    """Submit PBS jobs.

    For each parameter set, it will be checked first if there is already a
    process working on it (using *qstat*).

    Make sure to use *create* first to create missing datafiles and directories
    before submitting any jobs."""

    # parse command line options
    op = optparse.OptionParser(usage='%prog submit [options] CONFFILE ' +
                                     '[CONFFILE2 ...]',
                               version=__version__,
                               description=submit.__doc__)
    op.add_option('-n', '--number', default=-1, type=int,
                  help='number of jobs to submit. If negative, submit all')
    op.add_option('-m', '--email', default='a',
                  help='send email when job begins (b), ends (e) or aborts ' +
                       '(a)')
    op.add_option('-M', '--email-address', dest='address',
                  default='d.jung@jacobs-university.de',
                  help='set email address')
    op.add_option('-d', '--delay', default=0, type=float,
                  help='set delay between job submissions (in seconds)')
    op.add_option('-Q', '--queue', default='standard', help='set queue')
    op.add_option('-t', '--test', default=False, action='store_true',
                  help='test mode, just create job script, but do not ' +
                       'submit it')
    op.add_option('-v', '--verbose', default=False, action='store_true',
                  help='verbose mode')
    op.add_option('--ignore-acc', dest='ignoreacc', default=False,
                  action='store_true',
                  help='ignore accuracy, do not look it up in the datafile')
    op.add_option('-p', '--param', default='',
                  help='filter parameters (define parameter subspace) in ' +
                       'the format "A=1,B=:5,C=3.7:8.2"')
    op.add_option('-q', '--quiet', default=False, action='store_true',
                  help='be quiet, do not even report submitted jobs')
    op.add_option('-f', '--force', default=False, action='store_true',
                  help='skip jobs that cannot be submitted')
    op.add_option('-s', '--sort', default=None,
                  help='sort parameter sets by the given parameter')
    op.add_option('-r', '--reverse', default=False, action='store_true',
                  help='reverse sorting order')
    if len(args) == 0:
        args = ['--help']
    opts, posargs = op.parse_args(args=list(args))
    if opts.quiet:
        opts.verbose = False

    # remember shell's working directory
    cwd = os.getcwd()

    # count the number of submitted jobs
    submit_count = 0

    try:
        # cycle all given configuration files
        do_break = False
        for conffile in conf_filenames(*posargs):
            conf = parse_conf(conffile)
            psets = filter_psets(compute_psets(conf), opts.param,
                                 conf['pnames'])
            keys = sorted(psets.keys())
            if opts.sort:
                keys = sorted(keys, key=lambda key: psets[key].get(opts.sort))
            if opts.reverse:
                keys.reverse()

            # go to working directory
            os.chdir(conf['WORKDIR'])

            # get queue information
            qdata = get_qdata()
            running = count_running(psets, qdata)
            diff_to_maxrun = None if conf['MAXRUN'] is None \
                else conf['MAXRUN']-running

            # cycle jobs/datafiles
            for key in keys:
                pset = psets[key]
                cmd = cmd_exec(conf, pset)

                # check if the MAXRUN value has been reached
                if diff_to_maxrun and submit_count >= diff_to_maxrun:
                    if not opts.quiet:
                        maxrun = conf['MAXRUN']
                        print(f'pspace: submit: reached MAXRUN value ({maxrun})')
                        break

                # check if the number of jobs to submit has been reached
                if opts.number >= 0 and submit_count >= opts.number:
                    if opts.verbose:
                        print(f'pspace: submit: reached number of jobs to submit ({opts.number})')
                    do_break = True
                    break

                # make sure that the job is not already running
                if key in [job['Job_Name'] for job in qdata.values()]:
                    if opts.force:
                        if opts.verbose:
                            for job_id, job in qdata.items():
                                if key == job['Job_Name']:
                                    break
                            sys.stdout.write('pspace: submit: skipping ' +
                                             '"%s", ' % key +
                                             'already running (%s)\n' % job_id)
                            sys.stdout.flush()
                        continue
                    else:
                        print(f'pspace: submit: cannot submit "{key}", already running', file=sys.stderr)  # ({job_id})
                        sys.exit(1)

                # make sure that the datafile exists
                if not os.path.isfile(key):
                    if opts.force:
                        if opts.verbose:
                            sys.stdout.write('pspace: submit: skipping ' +
                                             '"%s", ' % key +
                                             'datafile not found\n')
                            sys.stdout.flush()
                        continue
                    else:
                        print(f'pspace: submit: datafile "{key}" not found', file=sys.stderr)
                        sys.exit(1)

                # sleep for a certain delay
                time.sleep(opts.delay)

                # check if target accuracy is already reached
                if not opts.ignoreacc:
                    acc = retry(get_acc, conf, pset, delay=2, retries=None)
                    acc_target = pset['ACC']
                    acc_target = int(acc_target) \
                        if int(acc_target) == acc_target else float(acc_target)
                    op = conf['CMD_ACC_OP']  # pset['OP']  # can be <, >, <=,
                                                           # >=, ==, !=
                    comparison = compare(acc, acc_target, op)
                    if acc is not None and comparison:
                        if opts.verbose:
                            print(f'pspace: submit: skipping "{key}", ' +
                                  f'target accuracy already reached ({acc_target})',
                                  file=sys.stderr)
                        continue

                # create temporary job script
                with open('job.temp', 'w') as f:
                    # write header
                    f.write('#!/bin/sh\n')

                    # set email options
                    if opts.email:
                        f.write('#PBS -m %s\n' % opts.email)
                    if opts.address:
                        f.write('#PBS -M %s\n' % opts.address)

                    # set job name
                    # important! serves as identification of the job
                    f.write('#PBS -N %s\n' % key)

                    # set working directory
                    f.write('#PBS -d %s\n' % conf['WORKDIR'])

                    # redirect standard output and standard error streams
                    without_ext = key.rsplit('.')[0] if '.' in key else key
                    #without_ext_abs = os.path.abspath(without_ext)
                    f.write('#PBS -o eo-%s.out\n'
                            % without_ext.replace('/', '-'))
                    f.write('#PBS -e eo-%s.err\n'
                            % without_ext.replace('/', '-'))

                    # set number of nodes and processors per node
                    f.write('#PBS -l nodes=1:ppn=1\n')

                    # set queue
                    if opts.queue:
                        f.write('#PBS -q %s\n' % opts.queue)

                    #f.write('#PBS -r n\n')  # do not rerun the job if it fails

                    # append actual command
                    f.write('\n')
                    f.write('%s\n' % cmd)

                # submit the job script using "qsub"
                if not opts.test:
                    job_id = subprocess.check_output('qsub job.temp',
                                                     shell=True).strip()

                # report
                if not opts.quiet:
                    if opts.test:
                        sys.stdout.write('pspace: submit: would have ' +
                                         'submitted job "%s"\n' % key)
                    else:
                        sys.stdout.write('pspace: submit: submitted job ' +
                                         '"%s" (%s)\n' % (key, job_id))
                    sys.stdout.flush()

                # increase count
                submit_count += 1

            if do_break:
                break

    except KeyboardInterrupt:
        if not opts.quiet:
            print('pspace: submit: aborted by user')
    finally:
        # return to shell's original working directory
        os.chdir(cwd)


def delete(*args):
    """Delete jobs submitted to the batch system. Filter by parameter subspace,
    node name or job ID.

    Uses the PBS command *qdel*."""

    # parse command line options
    op = optparse.OptionParser(usage='%prog delete [options] CONFFILE ' +
                                     '[CONFFILE2 ...]',
                               version=__version__,
                               description=delete.__doc__)
    op.add_option('-p', '--param', default='',
                  help='filter by parameter subspace (valid example: ' +
                       '"A=1,B=:5,C=3.7:8.2")')
    op.add_option('-t', '--test', default=False, action='store_true',
                  help='test mode, just show which jobs would have been ' +
                       'deleted')
    op.add_option('-f', '--force', default=False, action='store_true',
                  help='never prompt')
    op.add_option('-v', '--verbose', default=False, action='store_true',
                  help='be verbose')
    op.add_option('-q', '--quiet', default=False, action='store_true',
                  help='be quiet, do not even report deleted jobs')
    op.add_option('-W', '--delay', default=60,
                  help='set delay between the sending of the SIGTERM and ' +
                       'SIGKILL signals in seconds ' +
                       '(time that a job is granted to shutdown itself in a ' +
                       'controlled way)')
    op.add_option('-R', '--running', default=False, action='store_true',
                  help='delete only running jobs (job status "R")')
    op.add_option('-Q', '--queued', default=False, action='store_true',
                  help='delete only queued jobs (job status "Q")')
    #op.add_option('-i', '--id', default=None, type=int,
                  #help='filter by job ID')
    #op.add_option('-n', '--node', default='', help='filter by node name')
    if len(args) == 0:
        args = ['--help']
    opts, posargs = op.parse_args(args=list(args))
    if opts.quiet:
        opts.verbose = False

    # remember shell's working directory
    cwd = os.getcwd()

    try:
        for conffile in conf_filenames(*posargs):
            conf = parse_conf(conffile)
            psets = filter_psets(compute_psets(conf), opts.param,
                                 conf['pnames'])
            jobnames = sorted(psets.keys())

            # go to working directory
            os.chdir(conf['WORKDIR'])

            # get queue information, get names of the jobs in the queue
            qdata = get_qdata()
            qjobs = {}
            for job_id, jobinfo in qdata.items():
                # filter according to job status
                if opts.running or opts.queued:
                    if jobinfo.get('job_state', '') == 'R' \
                            and not opts.running:
                        continue
                    if jobinfo.get('job_state', '') == 'Q' and not opts.queued:
                        continue

                qjobs[jobinfo['Job_Name']] = job_id

            # cycle job names that have to be deleted (if found in queue)
            for jobname in jobnames:
                if jobname in qjobs.keys():
                    # found a candidate
                    job_id = qjobs[jobname]
                    if opts.test:
                        if not opts.quiet:
                            sys.stdout.write('pspace: delete: would have ' +
                                             'deleted job ' +
                                             '"%s" (%s)\n' % (jobname, job_id))
                            sys.stdout.flush()
                        continue

                    # prompt
                    if not opts.force:
                        message = 'pspace: delete: delete job ' + \
                            '"%s" (%s) [%s]? ' % (jobname, job_id,
                                                  qdata[job_id]['job_state'])
                        answer = input(message).lower()
                        if not answer or not 'yes'.startswith(answer):
                            continue

                    # delete the job
                    subprocess.check_output('qdel -W%i %s'
                                            % (int(opts.delay),
                                               qjobs[jobname]), shell=True)
                    if not opts.quiet:
                        sys.stdout.write('pspace: delete: deleted job ' +
                                         '"%s" (%s) [%s]\n'
                                         % (jobname, job_id,
                                            qdata[job_id]['job_state']))
                        sys.stdout.flush()
                else:
                    ## selected job was not found in the queue
                    #if not opts.force:
                        #print(f'pspace: delete: job "{jobname}" not found', file=sys.stderr)
                        #sys.exit(1)
                    if opts.verbose:
                        sys.stdout.write(f'pspace: delete: skipping "{jobname}", job not found\n')
                        sys.stdout.flush()

    except KeyboardInterrupt:
        if not opts.quiet:
            print('pspace: delete: aborted by user')
    finally:
        # return to shell's original working directory
        os.chdir(cwd)


def info(*args):
    """Show information about a given configuration file and its parameter
    space.

    This command shows general information about a parameter space, i.e. one
    line per given configuration file. Use *list* to list information about
    every single parameter set, i.e., one line per parameter set.

    It can be specified which columns the output should contain (and their
    order) using the --display option. If --display contains a plus sign (+),
    all columns defined thereafter are added to the already defined (or
    default) columns. If --display contains a minus sign (-), all columns
    defined thereafter are removed from the already defined (or default)
    columns. For example, you can specify "--display +db-c" to add columns for
    the directory size and the working directory to the default output, but
    remove the cardinality column.

    Possible characters for the --display option:

    n
        name of the directory where the configuration file resides
    N
        relative path to the directory where the configuration file resides
    c
        cardinality (number of parameter combinations)
    e
        pattern for the execution command
    f
        pattern for creating the datafile
    a
        pattern for obtaining the accuracy
    o
        comparison operator used to decide if accuracy has been reached
    F
        pattern for the datafile
    M
        number of jobs being submitted at the same time (MAXRUN)
    d
        working directory (WORKDIR)
    D
        working directory (WORKDIR), absolute path
    b
        size of the directory (where the configuration file is in) in kilobytes
    s
        number of submitted jobs (no matter in which state)
    R
        number of running jobs (submitted and with status R)
    Q
        number of queued jobs (submitted and with status Q)
    C
        number of completed jobs (submitted and with status C)
    E
        number of exiting jobs (submitted and with status E)
    H
        number of held jobs (submitted and with status H)
    T
        number of moving jobs (submitted and with status T)
    W
        number of waiting jobs (submitted and with status W)
    S
        number of suspended jobs (submitted and with status S)
    t
        number of jobs that reached their target accuracy (so they finished)"""

    # parse command line options
    op = optparse.OptionParser(usage='%prog info [options] CONFFILE ' +
                                     '[CONFFILE2 ...]',
                               version=__version__, description=info.__doc__)
    output_default = 'NcsRQ'
    op.add_option('-d', '--display', dest='output', default=output_default,
                  help='set output columns (see documentation for possible ' +
                       'characters)')
    op.add_option('-t', '--titles', default=False, action='store_true',
                  help='show column titles')
    op.add_option('-c', '--columns', default=None, type=int,
                  help='set number of columns. If None, detect automatically')
    op.add_option('-p', '--param', default='',
                  help='filter parameters (define parameter subspace) in ' +
                       'the format "A=1,B=:5,C=3.7:8.2"')
    op.add_option('-q', '--quiet', default=False, action='store_true',
                  help='be quiet, do not print warning that user aborted')
    op.add_option('-u', '--user', default=getpass.getuser(),
                  help='set user (job owner), defaults to current user')
    op.add_option('-b', '--bar', default=False, action='store_true',
                  help='show progress bar (only when fetching accuracy ' +
                       'information from the datafiles, i.e. --display ' +
                       'includes "t")')
    op.add_option('-s', '--strict', default=False, action='store_true',
                  help='do not skip configuration files with syntax errors')
    if len(args) == 0:
        args = ['--help']
    opts, posargs = op.parse_args(args=list(args))

    # understand output option
    if one_of_in('+-', opts.output):
        if opts.output and opts.output[0] in '+-':
            new_opt = output_default
        else:
            new_opt = ''
        mode = ''
        for char in opts.output:
            if char == '+':
                mode = '+'
            elif char == '-':
                mode = '-'
            else:
                if mode == '+':
                    new_opt += char
                elif mode == '-':
                    new_opt = new_opt.replace(char, '')
                else:
                    new_opt += char
        opts.output = new_opt

    # remember shell's working directory
    cwd = os.getcwd()

    # define column titles
    ctitles = dict(c='CARDIN', e='CMD_EXEC', f='CMD_FILE', a='CMD_ACC',
                   F='DATAFILE', M='MAXRUN', d='WORKDIR', b='SIZE', s='SUB',
                   R='R', Q='Q', C='C', E='E', H='H', T='T', W='W', S='S',
                   t='FINISHED', D='WORKDIR', n='NAME', o='CMD_ACC_OP',
                   N='RELPATH')

    # get columns
    if opts.columns is None:
        opts.columns = get_cols()

    # get queue data from the batch system using "qstat -f1"
    # filter jobs of the specified user
    if one_of_in('sRQCEHTWS', opts.output):
        qdata = {}
        for job_id, job_info in get_qdata().items():
            if job_info['Job_Owner'].split('@')[0] == opts.user:
                qdata[job_id] = job_info

    # initialize data structures
    titles = []
    chars = []
    values = []

    try:
        for conffile in conf_filenames(*posargs, force=True):
            try:
                conf = parse_conf(conffile)
            except:
                if opts.strict:
                    raise
                continue
            psets = \
                filter_psets(compute_psets(conf), opts.param, conf['pnames'])
            datafiles = sorted(psets.keys())

            # initialize row datastructure
            row_values = []

            # go to working directory
            os.chdir(conf['WORKDIR'])

            # fetch different types of information
            if one_of_in('sRQCEHTWS', opts.output):
                # filter only qdata jobs of this configuration file
                qdata_conf = {}
                for job_id, job_info in qdata.items():
                    if job_info['Job_Name'] in datafiles:
                        qdata_conf[job_id] = job_info

                # count how many jobs are in each state
                state_count = dict(R=0, Q=0, C=0, E=0, H=0, T=0, W=0, S=0)
                for job_info in qdata_conf.values():
                    if job_info['Job_Name'] in datafiles \
                            and 'job_state' in job_info:
                        state = job_info['job_state']
                        if state in state_count:
                            state_count[state] += 1

            if 'b' in opts.output:
                # get size of the directory
                confdir = os.path.dirname(conffile)
                try:
                    dirsize = \
                        subprocess.check_output('du -s %s' % confdir,
                                                shell=True,
                                                stderr=subprocess.STDOUT)\
                        .strip()
                    #print dirsize,
                    dirsize = dirsize.split()[0]
                    #print dirsize,
                    dirsize = int(dirsize)  # float(dirsize)/1024
                    #print dirsize
                except:
                    dirsize = ''
            if 'n' in opts.output:
                dirname = os.path.basename(os.path.dirname(conffile))
            if 'N' in opts.output:
                relpath = os.path.relpath(os.path.dirname(conffile))
            if 't' in opts.output:
                # obtain accuracy for all jobs, count how many have reached
                # their target accuracy (i.e., how many are finished)
                count_finished = 0
                dirname = os.path.basename(os.path.dirname(conffile))
                with progmon.Bar(len(datafiles), text=dirname,
                                  verbose=opts.bar) as bar:
                    for datafile in datafiles:
                        pset = psets[datafile]
                        acc = get_acc(conf, pset)
                        target = pset['ACC']
                        if acc is not None and acc <= target:
                            count_finished += 1
                        bar.step()

            # collect row values
            for char in opts.output:
                if char == 'n':
                    row_values.append(dirname)
                elif char == 'N':
                    row_values.append(relpath)
                elif char == 'c':
                    row_values.append(len(psets))
                elif char == 'e':
                    row_values.append(conf['CMD_EXEC'])
                elif char == 'f':
                    row_values.append(conf['CMD_FILE'])
                elif char == 'a':
                    row_values.append(conf['CMD_ACC'])
                elif char == 'o':
                    row_values.append(conf['CMD_ACC_OP'])
                elif char == 'F':
                    row_values.append(conf['DATAFILE'])
                elif char == 'M':
                    maxrun = conf['MAXRUN']
                    row_values.append(maxrun if maxrun is not None else '')
                elif char == 'd':
                    row_values.append(conf['WORKDIR_RAW'])
                elif char == 'D':
                    row_values.append(conf['WORKDIR'])
                elif char == 'b':
                    row_values.append(dirsize)
                elif char == 's':
                    row_values.append(len(qdata_conf))
                elif char == 'R':
                    row_values.append(state_count[char])
                elif char == 'Q':
                    row_values.append(state_count[char])
                elif char == 'C':
                    row_values.append(state_count[char])
                elif char == 'E':
                    row_values.append(state_count[char])
                elif char == 'H':
                    row_values.append(state_count[char])
                elif char == 'T':
                    row_values.append(state_count[char])
                elif char == 'W':
                    row_values.append(state_count[char])
                elif char == 'S':
                    row_values.append(state_count[char])
                elif char == 't':
                    row_values.append(count_finished)
                else:
                    print(f'pspace: info: unknown character "{char}" in --display', file=sys.stderr)
                    sys.exit(1)

            # collect values
            values.append(row_values)

    except KeyboardInterrupt:
        if not opts.quiet:
            print('pspace: info: aborted by user')
    finally:
        # return to shell's original working directory
        os.chdir(cwd)

    # collect titles and column specifiers
    for char in opts.output:
        titles.append(ctitles[char])
        chars.append(char)

    # compute columnwidths
    colwidths = []
    for colindex in range(len(titles)):
        valwidths = [len(str(row_values[colindex]))
                     if row_values[colindex] is not None else 0
                     for row_values in values]
        colwidth = max(valwidths) if valwidths else 0
        if opts.titles and len(titles[colindex]) > colwidth:
            colwidth = len(titles[colindex])
        colwidths.append(colwidth)

    # print information, even if incomplete (if aborted by user)
    if opts.titles:
        parts = []
        for title, colwidth in zip(titles, colwidths):
            parts.append('%- *s' % (colwidth, title))
        line = ' '.join(parts)
        print(line[:(opts.columns-1)])
    for row_values in values:
        parts = []
        for value, colwidth in zip(row_values, colwidths):
            if isinstance(value, int):
                parts.append('% *s' % (colwidth, str(value)))
            elif value is None:
                parts.append(' '*colwidth)
            else:
                parts.append('%- *s' % (colwidth, str(value)))
        line = ' '.join(parts)
        print(line[:(opts.columns-1)])


def jlist(*args):
    """List information about jobs.

    It can be specified which columns the output should contain (and their
    order) using the --display option. If --display contains a plus sign (+),
    all columns defined thereafter are added to the already defined (or
    default) columns. If --display contains a minus sign (-), all columns
    defined thereafter are removed from the already defined (or default)
    columns. For example, you can specify "--display +Ab-i" to add accuracy and
    filesize information to the default output, but remove the job ID column.

    Possible characters for the --display option:

    n
        job name (path to the associated datafile)
    i
        job ID (if job is currently submitted to the batch system)
    e
        execution command
    f
        command to create the datafile
    a
        command to obtain the data accuracy
    A
        current data accuracy (datafile lookup, costs time)
    t
        target accuracy
    p
        parameter set
    s
        PBS job state (if job is currently submitted to the batch system)
    b
        size of the datafile in kilobytes

    Possible characters for the --filter option:

    f
        show only finished jobs (already reached target accuracy)
    F
        show only unfinished jobs (not yet reached target accuracy)
    s
        show only jobs submitted to the batch system
    S
        show only jobs currently not submitted to the batch system
    r
        "restart", same as "FS" (not finished and also currently not submitted
        to the batch system), i.e. these jobs should be restarted
    R
        show only running jobs (PBS job state "R")
    Q
        show only queued jobs (PBS job state "Q")
    C
        show only completed jobs (PBS job state "C")
    E
        show only exited jobs (PBS job state "E")
    H
        show only held jobs (PBS job state "H")
    T
        show only moved jobs (PBS job state "T")
    W
        show only waiting jobs (PBS job state "W")
    P
        show only suspended jobs (PBS job state "S")"""

    # parse command line options
    op = optparse.OptionParser(usage='%prog list [options] CONFFILE ' +
                                     '[CONFFILE2 ...]',
                               version=__version__, description=jlist.__doc__)
    output_default = 'nis'
    op.add_option('-d', '--display', dest='output', default=output_default,
                  help='set output columns (see documentation for possible ' +
                       'characters)')
    op.add_option('-t', '--titles', default=False, action='store_true',
                  help='show column titles')
    op.add_option('-c', '--columns', default=None, type=int,
                  help='set number of columns. If None, detect automatically')
    op.add_option('-p', '--param', default='',
                  help='filter parameters (define parameter subspace) in ' +
                       'the format "A=1,B=:5,C=3.7:8.2"')
    op.add_option('-q', '--quiet', default=False, action='store_true',
                  help='be quiet, do not print warning that user aborted')
    op.add_option('-u', '--user', default=getpass.getuser(),
                  help='set user (job owner), defaults to current user')
    op.add_option('-f', '--filter', default='', help='define filter criteria')
    op.add_option('-b', '--bar', default=False, action='store_true',
                  help='show progress bar')
    if len(args) == 0:
        args = ['--help']
    opts, posargs = op.parse_args(args=list(args))

    # understand output option
    if one_of_in('+-', opts.output):
        if opts.output and opts.output[0] in '+-':
            new_opt = output_default
        else:
            new_opt = ''
        mode = ''
        for char in opts.output:
            if char == '+':
                mode = '+'
            elif char == '-':
                mode = '-'
            else:
                if mode == '+':
                    new_opt += char
                elif mode == '-':
                    new_opt = new_opt.replace(char, '')
                else:
                    new_opt += char
        opts.output = new_opt

    # remember shell's working directory
    cwd = os.getcwd()

    # define column titles
    ctitles = dict(n='NAME', i='ID', e='CMD_EXEC', f='CMD_FILE', a='CMD_ACC',
                   A='ACC', t='TARGET', p='PSET', s='STATE', b='SIZE')

    # get columns
    if opts.columns is None:
        opts.columns = get_cols()

    # get queue data from the batch system using "qstat -f1"
    # filter jobs of the specified user
    if one_of_in('is', opts.output) or opts.filter:
        qdata = {}
        for job_id, job_info in get_qdata().items():
            if job_info['Job_Owner'].split('@')[0] == opts.user:
                qdata[job_id] = job_info

    try:
        for conffile in conf_filenames(*posargs):
            conf = parse_conf(conffile)
            psets = filter_psets(compute_psets(conf), opts.param,
                                 conf['pnames'])
            datafiles = sorted(psets.keys())

            # initialize data structures
            titles = []
            chars = []
            values = []

            # go to working directory
            os.chdir(conf['WORKDIR'])

            # cycle jobs/datafiles
            dirname = os.path.basename(os.path.dirname(conffile))
            with progmon.Bar(len(datafiles), text=dirname, verbose=opts.bar) \
                    as bar:
                for datafile in datafiles:
                    pset = psets[datafile]

                    # initialize row datastructure
                    row_values = []

                    # fetch different types of information
                    if 'b' in opts.output:
                        # get size of the datafile
                        try:
                            filesize = \
                                subprocess.\
                                check_output('du -s %s' % datafile,
                                             shell=True,
                                             stderr=subprocess.STDOUT).strip()
                            filesize = filesize.split()[0]
                            filesize = int(filesize)  # float(dirsize)/1024
                        except:
                            filesize = ''
                    if 'i' in opts.output:
                        # get job ID
                        for job_id, job_info in qdata.items():
                            if job_info['Job_Name'] == datafile:
                                # remember the variable job_id after the
                                # for-loop has been left
                                found_job_id = job_id
                                break
                        else:
                            # looks like the job is currently not submitted to
                            # the batch system
                            found_job_id = ''
                    if 's' in opts.output or opts.filter:
                        # get job state
                        for job_id, job_info in qdata.items():
                            if job_info['Job_Name'] == datafile:
                                job_state = job_info.get('job_state', '')
                                break
                        else:
                            # looks like the job is currently not submitted to
                            # the batch system
                            job_state = ''
                    if 'p' in opts.output:
                        # format parameter set
                        parts = []
                        for pname in conf['pnames']:
                            parts.append('%s=%g' % (pname, pset[pname]))
                        parameter_set = ','.join(parts)

                    # filter option, part 1 (for which the accuracy is not
                    # needed)
                    if opts.filter:
                        # filter submitted/unsubmitted
                        job_names = [job_info['Job_Name']
                                     for job_info in qdata.values()]
                        if 's' in opts.filter and not datafile in job_names:
                            bar.step()
                            continue
                        if 'S' in opts.filter and datafile in job_names:
                            bar.step()
                            continue

                        # filter by job state
                        if 'R' in opts.filter and job_state != 'R' \
                                or 'Q' in opts.filter and job_state != 'Q' \
                                or 'C' in opts.filter and job_state != 'C' \
                                or 'E' in opts.filter and job_state != 'E' \
                                or 'W' in opts.filter and job_state != 'W' \
                                or 'H' in opts.filter and job_state != 'H' \
                                or 'T' in opts.filter and job_state != 'T' \
                                or 'P' in opts.filter and job_state != 'S':
                            bar.step()
                            continue

                        # filter jobs that do not have to be restarted, part 1
                        if 'r' in opts.filter and datafile in job_names:
                            # job is currently running, so no need to restart
                            # it right now
                            bar.step()
                            continue

                    # fetch additional information (get accuracy from datafile)
                    if 'A' in opts.output or one_of_in('fFr', opts.filter):
                        # obtain current data accuracy
                        try:
                            data_accuracy = get_acc(conf, pset)
                        except:
                            data_accuracy = ''

                    # filter option, part 2 (for which the accuracy has to be
                    # known)
                    if one_of_in('fFr', opts.filter):
                        # filter finished/unfinished
                        finished = data_accuracy \
                            and data_accuracy <= pset['ACC']
                        if 'f' in opts.filter and not finished:
                            bar.step()
                            continue
                        if 'F' in opts.filter and finished:
                            bar.step()
                            continue

                        # filter jobs that do not have to be restarted, part 2
                        if 'r' in opts.filter and finished:
                            bar.step()
                            continue

                    # collect row values
                    for char in opts.output:
                        if char == 'n':
                            row_values.append(datafile)
                        elif char == 'i':
                            row_values.append(found_job_id)
                        elif char == 's':
                            row_values.append(job_state)
                        elif char == 'b':
                            row_values.append(filesize)
                        elif char == 'e':
                            row_values.append(cmd_exec(conf, pset))
                        elif char == 'f':
                            row_values.append(cmd_file(conf, pset))
                        elif char == 'a':
                            row_values.append(cmd_acc(conf, pset))
                        elif char == 'A':
                            row_values.append(data_accuracy)
                        elif char == 't':
                            row_values.append(pset['ACC'])
                        elif char == 'p':
                            row_values.append(parameter_set)
                        else:
                            print(f'pspace: list: unknown character "{char}" in --display', file=sys.stderr)
                            sys.exit(1)

                    # collect values
                    values.append(row_values)
                    bar.step()

            # collect titles and column specifiers
            for char in opts.output:
                titles.append(ctitles[char])
                chars.append(char)

            # compute columnwidths
            colwidths = []
            for colindex in range(len(titles)):
                valwidths = [len(str(row_values[colindex]))
                             if row_values[colindex] is not None else 0
                             for row_values in values]
                colwidth = max(valwidths) if valwidths else 0
                if opts.titles and len(titles[colindex]) > colwidth:
                    colwidth = len(titles[colindex])
                colwidths.append(colwidth)

            # print information, even if incomplete (if aborted by user)
            if opts.titles:
                parts = []
                for title, colwidth in zip(titles, colwidths):
                    parts.append('%- *s' % (colwidth, title))
                line = ' '.join(parts)
                print(line[:(opts.columns-1)])
            for row_values in values:
                parts = []
                for value, colwidth in zip(row_values, colwidths):
                    if isinstance(value, (int, float)):
                        parts.append('% *s' % (colwidth, str(value)))
                    elif value is None:
                        parts.append(' '*colwidth)
                    else:
                        parts.append('%- *s' % (colwidth, str(value)))
                line = ' '.join(parts)
                print(line[:(opts.columns-1)])

    except KeyboardInterrupt:
        if not opts.quiet:
            print('pspace: list: aborted by user')
    finally:
        # return to shell's original working directory
        os.chdir(cwd)


def fnames(*args):
    """Show names (paths) of the datafiles for the selected jobs (which also
    serve as job names when submitted to the batch system).

    Shortcut for "list --display n".

    Options are the same as for *list* except for the --display option having
    no effect. See the documentation of the *list* command for details"""
    if args:
        args += ('--display', 'n')
        jlist(*args)
    else:
        print(fnames.__doc__)


def cardinality(*args):
    """Compute cardinality of the defined parameter space (number of parameter
    combinations).

    Shortcut for "info --display a".

    Options are the same as for *info* except for the --display option having
    no effect. See the documentation of the *info* command for details."""
    if args:
        args += ('--display', 'c')
        info(*args)
    else:
        print(cardinality.__doc__)


def purge(*args):
    """Delete empty datafiles. If directories end up empty, delete them as
    well.

    Datafiles of jobs that are currently submitted will be skipped."""

    raise NotImplementedError
    ### problem: have to use external knowledge (how to use h5ls or something)

    ## parse command line options
    #op = optparse.OptionParser(usage='%prog purge [options] CONFFILE ' +
    #                                 '[CONFFILE2 ...]',
    #                           version=__version__,
    #                           description=purge.__doc__)
    #op.add_option('-i', '--ignore', default='__scell__,__param__,scell,param',
    #              help='ignore given dataset names, i.e. purge even if ' +
    #                   'datasets with these names exist in the file')
    ##op.add_option('-n', '--number', default=-1, type=int,
    #              #help='number of datafiles to delete. If negative, delete '
    #              + #'all')
    ##op.add_option('-d', '--delay', default=0, type=float,
    #              #help='set delay between file lookups (in seconds)')
    ##op.add_option('-t', '--test', default=False, action='store_true',
    #              #help='test mode, just list files which would have been ' +
    #                   #'deleted')
    ##op.add_option('-v', '--verbose', default=False, action='store_true',
    #              #help='verbose mode, report every deleted file')
    #op.add_option('-p', '--param', default='',
    #              help='filter parameters (define parameter subspace) in ' +
    #                   'the format "A=1,B=:5,C=3.7:8.2"')
    #if len(args) == 0:
    #    args = ['--help']
    #opts, posargs = op.parse_args(args=list(args))

    ## remember shell's working directory
    #cwd = os.getcwd()

    ## count the number of submitted jobs
    #submit_count = 0

    #try:
    #    # cycle all given configuration files
    #    do_break = False
    #    for conffile in conf_filenames(*posargs):
    #        conf = parse_conf(conffile)
    #        psets = filter_psets(compute_psets(conf), opts.param,
    #                             conf['pnames'])
    #        keys = sorted(psets.keys())

    #        # go to working directory
    #        os.chdir(conf['WORKDIR'])

    #        # get queue information
    #        qdata = get_qdata()

    #    ### CONTINUE HERE ###

    #    # cycle jobs/datafiles
    #    for key in keys:
    #        pset = psets[key]
    #        cmd = cmd_exec(conf, pset)

    #        # check if the MAXRUN value has been reached
    #        if diff_to_maxrun and submit_count >= diff_to_maxrun:
    #            if not opts.quiet:
    #                print(f'pspace: submit: reached MAXRUN value ({conf['MAXRUN']})')
    #                break

    #        # check if the number of jobs to submit has been reached
    #        if opts.number >= 0 and submit_count >= opts.number:
    #            if opts.verbose:
    #                print(f'pspace: submit: reached number of jobs to submit ({opts.number})')
    #            do_break = True
    #            break

    #        # make sure that the job is not already running
    #        if key in [job['Job_Name'] for job in qdata.values()]:
    #            if opts.force:
    #                    if opts.verbose:
    #                        for job_id, job in qdata.items():
    #                            if key == job['Job_Name']:
    #                                break
    #                        sys.stdout.write('pspace: submit: skipping "%s", '
    #                        % key +\ 'already running (%s)\n' % job_id)
    #                        sys.stdout.flush()
    #                    continue
    #            else:
    #                print('pspace: submit: cannot submit "%s", ' % key +\
    #                    'already running' # (%s) % job_id, file=sys.stderr)
    #                sys.exit(1)

    #        # make sure that the datafile exists
    #        if not os.path.isfile(key):
    #            if opts.force:
    #                if opts.verbose:
    #                    sys.stdout.write('pspace: submit: skipping "%s",
    #                    datafile '+\ 'not found\n' % key)
    #                    sys.stdout.flush()
    #                continue
    #            else:
    #                print(f'pspace: submit: datafile "{key}" not found', file=sys.stderr)
    #                sys.exit(1)

    #        # sleep for a certain delay
    #        time.sleep(opts.delay)

    #        # check if target accuracy is already reached
    #        if not opts.ignoreacc:
    #            acc = retry(get_acc, conf, pset, delay=2, retries=None)
    #            acc_target = pset['ACC']
    #            acc_target = int(acc_target) if int(acc_target) == acc_target
    #            \ else float(acc_target)
    #            op = conf['CMD_ACC_OP'] #pset['OP'] # can be <, >, <=, >=, ==,
    #            !=
    #            comparison = compare(acc, acc_target, op)
    #            if acc is not None and comparison:
    #                if opts.verbose:
    #                    print('pspace: submit: skipping "%s", ' % key +
    #                          'target accuracy already reached (%g)' %
    #                          acc_target, file=sys.stderr)
    #                continue

    #        # create temporary job script
    #        with open('job.temp', 'w') as f:
    #            # write header
    #            f.write('#!/bin/sh\n')

    #            # set email options
    #            if opts.email:
    #                f.write('#PBS -m %s\n' % opts.email)
    #            if opts.address:
    #                f.write('#PBS -M %s\n' % opts.address)

    #            # set job name
    #            # important! serves as identification of the job
    #            f.write('#PBS -N %s\n' % key)

    #            # set working directory
    #            f.write('#PBS -d %s\n' % conf['WORKDIR'])

    #            # redirect standard output and standard error streams
    #            without_ext = key.rsplit('.')[0] if '.' in key else key
    #            #without_ext_abs = os.path.abspath(without_ext)
    #            f.write('#PBS -o eo-%s.out\n' % without_ext.replace('/', '-'))
    #            f.write('#PBS -e eo-%s.err\n' % without_ext.replace('/', '-'))

    #            # set number of nodes and processors per node
    #            f.write('#PBS -l nodes=1:ppn=1\n')

    #            # set queue
    #            if opts.queue: f.write('#PBS -q %s\n' % opts.queue)

    #            #f.write('#PBS -r n\n') # do not rerun the job if it fails

    #            # append actual command
    #            f.write('\n')
    #            f.write('%s\n' % cmd)

    #        # submit the job script using "qsub"
    #        if not opts.test:
    #            job_id = subprocess.check_output('qsub job.temp',
    #            shell=True).strip()

    #        # report
    #        if not opts.quiet:
    #            if opts.test:
    #                sys.stdout.write('pspace: submit: would have submitted job
    #                "%s"\n' \ % key)
    #            else:
    #                sys.stdout.write('pspace: submit: submitted job "%s"
    #                (%s)\n' \ % (key, job_id))
    #            sys.stdout.flush()

    #        # increase count
    #        submit_count += 1

    #    if do_break:
    #        break

    #except KeyboardInterrupt:
    #    if not opts.quiet:
    #        print('pspace: submit: aborted by user')
    #finally:
    #    # return to shell's original working directory
    #    os.chdir(cwd)


def users(*args):
    """List job owners of submitted jobs."""
    qdata = get_qdata()
    userdata = {}
    for job in qdata.values():
        user, project = job['Job_Owner'].split('@', 1)
        project = project.split('.', 1)[0].upper()
        if user not in userdata:
            userdata[user] = {}
            userdata[user]['project'] = project
            userdata[user]['S'] = 0
            userdata[user]['R'] = 0
            userdata[user]['Q'] = 0
            userdata[user]['queues'] = set()
        userdata[user]['S'] += 1
        state = job['job_state']
        if state == 'R':
            userdata[user]['R'] += 1
        elif state == 'Q':
            userdata[user]['Q'] += 1
        userdata[user]['queues'].add(job['queue'])

    # replace sets by strings, sort queues by alphabet
    for user in userdata.keys():
        qset = userdata[user]['queues']
        qlist = sorted(qset)
        qstring = ', '.join(qlist)
        userdata[user]['queues'] = qstring

    # sort by user
    keys = sorted(userdata.keys())
    out = {}
    for user in keys:
        out[user] = userdata[user]

    # display
    print(clitable.dord(out, rowtitles=True, width=80))


def queues(*args):
    """List queues and their usage."""
    qdata = get_qdata()
    data = {}
    for job in qdata.values():
        queue = job['queue']
        if queue not in data:
            data[queue] = {}
            data[queue]['S'] = 0
            data[queue]['R'] = 0
            data[queue]['Q'] = 0
            data[queue]['users'] = set()
        data[queue]['S'] += 1
        state = job['job_state']
        if state == 'R':
            data[queue]['R'] += 1
        elif state == 'Q':
            data[queue]['Q'] += 1
        user = job['Job_Owner'].split('@', 1)[0]
        data[queue]['users'].add(user)

    # replace sets by strings, sort users by alphabet
    for queue in data.keys():
        uset = data[queue]['users']
        ulist = sorted(uset)
        ustring = ', '.join(ulist)
        data[queue]['users'] = ustring

    # sort by queue
    keys = sorted(data.keys())
    out = {}
    for queue in keys:
        out[queue] = data[queue]

    # display
    import easytable
    print(clitable.dord(out, rowtitles=True, width=80))


#=====================#
# Auxiliary functions #
#=====================#


def one_of_in(sequence, iterable):
    """Check if at least one item of the given sequence is contained in the
    given iterable."""
    for item in sequence:
        if item in iterable:
            return True
    return False


def retry(func, *args, **kwargs):
    """Call the function *func* with the given arguments and keyword arguments.
    If an exception is raised, wait for a certain delay and call it again.

    Special keyword arguments:

    retries
        number of retries (default: 1), None means infinity
    delay
        delay before next try in seconds (default: 1)"""

    # fetch special keyword arguments
    delay = float(kwargs.pop('delay', 1.))
    retries = kwargs.pop('retries', 1)
    retries = int(retries) if retries is not None else None

    tries = -1
    while tries < retries or retries is None:
        try:
            return func(*args, **kwargs)
        except:
            if retries is not None:
                tries += 1
                if tries >= retries:
                    raise
            time.sleep(delay)


def filter_psets(psets, opts_param, pnames=None):
    """From the given parameter sets *psets*, filter only those parameters that
    are specified in the given --param option string. Return the corresponding
    parameter subspace.  Only parameter names specified in the list *pnames*
    are allowed (if given).  Valid examples are "J=1", "J=1,L=10", "J=7:,L=10",
    "J=3:8,L=10"."""

    # parse param option
    filterparams = {}
    for pair in opts_param.strip().split(','):
        pair = pair.strip()
        if not pair:
            continue
        try:
            key, value = pair.strip().split('=')
        except ValueError:
            print(f'pspace: bad NAME=VALUE pair "{pair}" in --param option', file=sys.stderr)
            sys.exit(1)

        key, value = key.strip(), value.strip()

        # check if this parameter has already occured
        if key in filterparams:
            print(f'pspace: double definition of parameter "{key}" in --param option', file=sys.stderr)
            sys.exit(1)

        # check if this parameter has been decleared in the configuration file
        if pnames and key not in pnames:
            print(f'pspace: undecleared parameter "{key}" in --param option', file=sys.stderr)
            sys.exit(1)

        # understand intervals
        if ':' in value:
            if value.count(':') > 1:
                print(f'pspace: bad interval definition "{value}" in --param option', file=sys.stderr)
                sys.exit(1)
            val1, val2 = value.split(':')
            val1, val2 = val1.strip(), val2.strip()
            try:
                val1 = float(val1) if val1 else None
            except ValueError:
                print(f'pspace: bad value "{val1}" in --param option', file=sys.stderr)
                sys.exit(1)
            try:
                val2 = float(val2) if val2 else None
            except ValueError:
                print(f'pspace: bad value "{val2}" in --param option', file=sys.stderr)
                sys.exit(1)
            filterparams[key] = (val1, val2)
        else:
            try:
                filterparams[key] = float(value)
            except ValueError:
                print(f'pspace: bad value "{value}" in --param option', file=sys.stderr)
                sys.exit(1)

    # filter parameter sets
    new_psets = {}
    #keys = sorted(psets.keys())
    #for key in keys:
    for key, pset in psets.items():
        #pset = psets[key]
        skip = False

        # skip parameter sets which do not meet the filter criteria
        for pname, pvalue in filterparams.items():
            if isinstance(pvalue, tuple):
                # interval given
                val1, val2 = pvalue
                if val1 is None and val2 is None:
                    continue
                elif val1 is None and pset[pname] <= val2:
                    continue
                elif val2 is None and pset[pname] >= val1:
                    continue
                elif pset[pname] >= val1 and pset[pname] <= val2:
                    continue
                else:
                    skip = True
                    break
            else:
                # single number given
                if str(pset[pname]) != str(pvalue):
                    skip = True
                    break
        if skip:
            # skip this parameter set as it does not meet the criteria
            continue

        # let this parameter set survive
        new_psets[key] = pset

    # return new (possibly fewer) parameter sets
    return new_psets


def count_running(psets, qdata):
    """Count how many of the given parameter sets *psets* are running according
    to the given *qstat* output (*qdata*)."""
    running = 0
    job_names = [job['Job_Name'] for job in qdata.values()]
    for key in psets:
        if key in job_names:
            running += 1
    return running


def get_acc(conf, pset, delay=2., retries=2):
    """Get accuracy from datafile."""
    
    cmd = cmd_acc(conf, pset)
    output = retry(subprocess.check_output, cmd, shell=True,
                   stderr=subprocess.STDOUT,
                   delay=delay, retries=retries).strip()

    # check if output is empty
    if not output:
        return None

    # check if output can not be interpreted as a float
    try:
        output = float(output)
    except:
        output = None

    # return float
    return output


def check_file(conf, pset, delay=2., retries=2):
    """Check datafile. If the system call returns an empty string, return
    *False*, otherwise, return *True*."""
    cmd = cmd_check(conf, pset)
    output = retry(subprocess.check_output, cmd, shell=True,
                   stderr=subprocess.STDOUT, delay=delay,
                   retries=retries).strip()
    return True if output else False


def cmd_file(conf, pset):
    """Return the command needed to create the datafile associated with the
    given parameter set, using the template from the configuration file
    information."""
    values = []
    for expr in conf['CMD_FILE_VALUES']:
        value = eval(expr, pset.copy())
        values.append(value)
    return conf['CMD_FILE'] % tuple(values)


def cmd_exec(conf, pset):
    """Return the execution command corresponding to the given parameter set,
    using the template from the configuration file information."""
    values = []
    for expr in conf['CMD_EXEC_VALUES']:
        value = eval(expr, pset.copy())
        values.append(value)
    return conf['CMD_EXEC'] % tuple(values)


def cmd_acc(conf, pset):
    """Return the command needed to obtain the accuracy from the datafile
    corresponding to the given parameter set, using the template from the
    configuration file information."""
    values = []
    for expr in conf['CMD_ACC_VALUES']:
        value = eval(expr, pset.copy())
        values.append(value)
    return conf['CMD_ACC'] % tuple(values)


def cmd_check(conf, pset):
    """Return the command needed to check the integrity of a datafile, using
    the template from the configuration file information."""
    values = []
    for expr in conf['CMD_CHECKFILE_VALUES']:
        value = eval(expr, pset.copy())
        values.append(value)
    return conf['CMD_CHECKFILE'] % tuple(values)


def get_qdata():
    """Get information about running jobs from PBS using the PBS command "qstat
    -f1"."""

    # get output from "qstat -f1"
    output = subprocess.check_output('qstat -f1', shell=True).strip()

    # define keys and data types of a job record
    job_keys = {'Job_Name': str, 'Job_Owner': str,
                'resources_used.cput': str, 'resources_used.mem': str,
                'resources_used.vmem': str, 'resources_used.walltime': str,
                'job_state': str, 'queue': str, 'server': str,
                'Checkpoint': str,
                'ctime': str, 'mtime': str, 'qtime': str, 'etime': str,
                'Error_Path': str, 'exec_host': str, 'Hold_Types': str,
                'Join_Path': str, 'Keep_Files': str, 'Mail_Points': str,
                'Mail_Users': str, 'Output_Path': str, 'Priority': int,
                'Rerunable': bool,
                'Resource_List.cput': str, 'Resource_List.nodect': str,
                'Resource_List.nodes': str, 'Resource_List.host': str,
                'Resource_List.mem': str, 'Resource_List.walltime': str,
                'Resource_List.ncpus': int,
                'session_id': int, 'submit_args': str, 'start_time': str,
                'start_count': int, 'fault_tolerant': bool,
                'submit_host': str, 'init_work_dir': str,
                'Walltime.Remaining': int,
                'x': str, 'Shell_Path_List': str, 'Variable_List': str,
                'interactive': str, 'exit_status': int}

    # parse output
    qdata = {}
    job_id = ''
    for line_index, line in enumerate(output.splitlines()):
        # skip empty lines
        if not line.strip():
            continue

        line = line.strip()
        words = line.split()
        if line.startswith('Job Id:'):
            # determine new job ID
            job_id = words[-1]

            # initialize new job data structure
            qdata[job_id] = {}
            for key, keytype in job_keys.items():
                qdata[job_id][key] = keytype()
        else:
            if not job_id:
                raise ValueError('job_id is empty')

            for key, keytype in job_keys.items():
                if words[0] == key:
                    value = line.split('=', 1)[1].strip()
                    qdata[job_id][key] = keytype(value)
                    break
            else:
                print(f'pspace: warning: unknown output of "qstat -f1" in line {line_index + 1} "{line}"', file=sys.stderr)
                key, value = line.split('=', 1)
                qdata[job_id][key] = value

    # return the information
    return qdata


def get_qdata_simple():
    """Get information about running jobs from PBS using the PBS command
    "qstat"."""

    # get output from "qstat"
    output = subprocess.check_output('qstat', shell=True).strip()

    # parse output
    qdata = []
    for line in output.splitlines():
        words = line.strip().split()
        if words[0] == 'Job' or words[0].startswith('--'):
            continue
        job_id, name, user, time_use, state, queue = words
        job_id_num = int(job_id.split('.')[0]) if '.' in job_id else None
        job_id_host = job_id.split('.')[1] if '.' in job_id else None
        qdata.append(dict(job_id=job_id, name=name, user=user,
                          time_use=time_use, state=state, queue=queue,
                          job_id_num=job_id_num, job_id_host=job_id_host))

    # return the information
    return qdata


def compute_psets(conf):
    """Compute and return all possible parameter combinations (parameter sets)
    of the given configuration information *conf*, together with filename of
    the corresponding datafile and accuracy target."""

    pnames = conf['pnames']
    psets = {}

    # iterate over parameter space definitions (may overlap)
    for pspace in conf['pspaces']:
        for pcomb in itertools.product(*[pspace['values'][key]
                                         for key in pnames]):
            pset = dict()
            for key, value in zip(pnames, pcomb):
                pset[key] = value
            datafile = name_datafile(conf, pset)
            pset['ACC'] = pspace['acc']
            #pset['OP'] = pspace['op']
            pset['FILE'] = datafile
            datafile = os.path.expanduser(datafile)
            if not datafile.startswith('/'):
                relpath = os.path.relpath(os.path.join(conf['WORKDIR'],
                                                       datafile))
                abspath = os.path.abspath(os.path.join(conf['WORKDIR'],
                                                       datafile))
            else:
                relpath = os.path.relpath(datafile)
                abspath = os.path.abspath(datafile)
            pset['RELPATH'] = relpath
            pset['ABSPATH'] = abspath

            # check if this parameter combination (datafile name) is already in
            # the list. If yes, choose the one with the better accuracy
            if datafile in psets:
                if compare(psets[datafile]['ACC'], pset['ACC'],
                           conf['CMD_ACC_OP']):
                    continue
            psets[datafile] = pset

    # return parameter sets
    return psets


def name_datafile(conf, pset):
    """Determine the name of the datafile belonging to the given parameter set
    *pset*.  The configuration information *conf* must be given."""
    values = []
    for expr in conf['DATAFILE_VALUES']:
        value = round(eval(expr, pset.copy()))
        values.append(value)
    return conf['DATAFILE'] % tuple(values) + '.h5'


def conf_filenames(*fileobjects, **kwargs):
    """Get the (absolute) paths to the configuration file specified by either
    directory names or by the files themselves. If *force* is *True*, silently
    ignore invalid files and directories."""

    force = kwargs.pop('force', False)
    if kwargs:
        raise KeyError(f'unknown keyword argument: {list(kwargs.keys())[0]}')

    #filenames = []
    out = []
    for fileobj in fileobjects:
        # check if file object exists at all
        relpath = fileobj
        fileobj = os.path.abspath(os.path.expanduser(fileobj))
        if not os.path.exists(fileobj):
            if force:
                continue
            print(f'pspace: {relpath}: no such file or directory', file=sys.stderr)
            sys.exit(1)

        # handle the case if the file object is a directory
        if os.path.isdir(fileobj):
            fileobj = fileobj.rstrip(os.path.sep)
            #dirname = os.path.basename(fileobj)
            fileobj = os.path.join(fileobj, 'pspace.conf')  # dirname+'.conf'

        # check if name of the file is "pspace.conf"
        if not os.path.basename(fileobj) == 'pspace.conf':
            if force:
                continue
            print(f'pspace: {fileobj}: wrong filename', file=sys.stderr)
            sys.exit(1)

        # check if file exists
        if not os.path.isfile(fileobj):
            if force:
                continue
            print(f'pspace: {fileobj}: no such file' % fileobj, file=sys.stderr)
            sys.exit(1)

        # return absolute path to configuration file
        out.append(fileobj)
    return out


def parse_conf(filename):
    """Load and parse a configuration file, given by *filename*. Return a
    configuration data structure. If a directory is given, look for a file
    named <dirname>.conf."""

    # define context constants
    #NONE = None
    PSPACE = 1

    # initialize context flags
    context = None
    indent = None

    # get absolute path to the configuration file
    filename, = conf_filenames(filename)

    # initialize data structure to hold configuration
    conf = dict(pnames=[], MAXRUN=None, WORKDIR='',
                DATAFILE='', DATAFILE_VALUES=[],
                CMD_EXEC='', CMD_EXEC_VALUES=[],
                CMD_FILE='', CMD_FILE_VALUES=[],
                CMD_ACC='', CMD_ACC_VALUES=[], CMD_ACC_OP='',
                CMD_CHECKFILE='', CMD_CHECKFILE_VALUES=[],
                pspaces=[])

    # parse file
    with open(filename, 'r') as f:
        for lind, line in enumerate(f.readlines()):
            # skip empty lines
            if not line.strip():
                continue

            # has the context been left?
            #print(lind + 1, context, line.strip(), line[0].isspace())
            if context and line.strip() and not line[0].isspace():
                context = None
                indent = None

            # check indent
            if context is not None:
                if indent is None:
                    indent = len(line) - len(line.lstrip())
                else:
                    if indent != len(line) - len(line.lstrip()):
                        print(f'pspace: {filename}:{lind + 1}: unexpected indent', file=sys.stderr)
                        sys.exit(1)

            # inside contexts there are special rules
            if context is None:
                # skip annotation lines
                if line.strip().startswith('#'):
                    continue

                # cut off annotations at the end of the line
                line = line.split('#', 1)[0]

                # parse parameter declarations
                if line.strip().split(None, 1)[0] == 'DECLARE':
                    for pname in line.replace(',', ' ').strip().split()[1:]:
                        pname = pname.strip()
                        if not pname:
                            continue

                        # check for already declared parameters
                        if pname in conf['pnames']:
                            print(f'pspace: {filename}:{lind + 1}: parameter "{pname}" already declared', file=sys.stderr)
                            sys.exit(1)

                        conf['pnames'].append(pname)

                # parse job submission limitations
                elif line.strip().split(None, 1)[0] == 'MAXRUN':
                    try:
                        _, number = line.strip().split()
                        number = int(number)
                    except:
                        conf_syntax_error(filename, lind)

                    # check if number is positive
                    if number < 1:
                        print(f'pspace: {filename}:{lind + 1}: MAXRUN must be positive integer', file=sys.stderr)
                        sys.exit(1)

                    # check if already specified
                    if conf['MAXRUN'] is not None:
                        print(f'pspace: {filename}:{lind + 1}: MAXRUN already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['MAXRUN'] = number

                # parse filename template
                elif line.strip().split(None, 1)[0] == 'WORKDIR':
                    _, workdir = line.strip().split(None, 1)

                    # check if already specified
                    if conf['WORKDIR']:
                        print(f'pspace: {filename}:{lind + 1}: WORKDIR already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['WORKDIR'] = os.path.abspath(os.path.expanduser(workdir))
                    conf['WORKDIR_RAW'] = workdir

                # parse filename template
                elif line.strip().split(None, 1)[0] == 'DATAFILE':
                    _, datafile = line.strip().split(None, 1)

                    # check if already specified
                    if conf['DATAFILE']:
                        print(f'pspace: {filename}:{lind + 1}: DATAFILE already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['DATAFILE'] = datafile

                # parse filename values
                elif line.strip().split(None, 1)[0] == 'DATAFILE_VALUES':
                    _, values = \
                        line.replace(',', ' ').strip().split(None, 1)
                    values = values.split()

                    # check if already specified
                    if conf['DATAFILE_VALUES']:
                        print(f'pspace: {filename}:{lind + 1}: DATAFILE_VALUES already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['DATAFILE_VALUES'] = values

                # parse execution command template
                elif line.strip().split(None, 1)[0] == 'CMD_EXEC':
                    _, cmd = line.strip().split(None, 1)

                    # check if already specified
                    if conf['CMD_EXEC']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_EXEC already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_EXEC'] = cmd

                # parse execution command values
                elif line.strip().split(None, 1)[0] == 'CMD_EXEC_VALUES':
                    _, values = \
                        line.replace(',', ' ').strip().split(None, 1)
                    values = values.split()

                    # check if already specified
                    if conf['CMD_EXEC_VALUES']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_EXEC_VALUES already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_EXEC_VALUES'] = values

                # parse command template for creating the datafiles
                elif line.strip().split(None, 1)[0] == 'CMD_FILE':
                    keyword, cmd = line.strip().split(None, 1)

                    # check if already specified
                    if conf['CMD_FILE']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_FILE already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_FILE'] = cmd

                # parse values for creating the datafiles
                elif line.strip().split(None, 1)[0] == 'CMD_FILE_VALUES':
                    keyword, values = \
                        line.replace(',', ' ').strip().split(None, 1)
                    values = values.split()

                    # check if already specified
                    if conf['CMD_FILE_VALUES']:
                        print(f'pspace: {filename}:{lind+1}: CMD_FILE_VALUES already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_FILE_VALUES'] = values

                # parse command template for checking datafiles
                elif line.strip().split(None, 1)[0] == 'CMD_CHECKFILE':
                    keyword, cmd = line.strip().split(None, 1)

                    # check if already specified
                    if conf['CMD_CHECKFILE']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_CHECKFILE already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_CHECKFILE'] = cmd

                # parse values for creating the datafiles
                elif line.strip().split(None, 1)[0] == 'CMD_CHECKFILE_VALUES':
                    keyword, values = \
                        line.replace(',', ' ').strip().split(None, 1)
                    values = values.split()

                    # check if already specified
                    if conf['CMD_CHECKFILE_VALUES']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_CHECKFILE_VALUES already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_CHECKFILE_VALUES'] = values

                # parse command template for getting the accuracy
                elif line.strip().split(None, 1)[0] == 'CMD_ACC':
                    keyword, cmd = line.strip().split(None, 1)

                    # check if already specified
                    if conf['CMD_ACC']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_ACC already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_ACC'] = cmd

                # parse values for getting the accuracy
                elif line.strip().split(None, 1)[0] == 'CMD_ACC_VALUES':
                    keyword, values = \
                        line.replace(',', ' ').strip().split(None, 1)
                    values = values.split()

                    # check if already specified
                    if conf['CMD_ACC_VALUES']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_ACC_VALUES already specified', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_ACC_VALUES'] = values

                # parse command template for setting operator for comparison
                elif line.strip().split(None, 1)[0] == 'CMD_ACC_OP':
                    keyword, op = line.strip().split(None, 1)

                    # check if already specified
                    if conf['CMD_ACC_OP']:
                        print(f'pspace: {filename}:{lind + 1}: CMD_ACC_OP already specified', file=sys.stderr)
                        sys.exit(1)

                    # check if allowed symbol
                    if not op in ('<', '>', '<=', '>=', '==', '!='):
                        print(f'pspace: {filename}:{lind + 1}: unknown comparison operator', file=sys.stderr)
                        sys.exit(1)

                    conf['CMD_ACC_OP'] = op

                # parse parameter space definitions
                elif line.strip() == 'PSPACE:':
                    # enter context
                    context = PSPACE
                    conf['pspaces'].append(dict(values=dict(), acc=None))

                # is there still something in that line? something unknown?
                elif line.strip():
                    conf_syntax_error(filename, lind)

                ### nothing else?

            elif context is PSPACE:
                # parse parameter values
                if line.strip().split(None, 1)[0] == 'PARAM':
                    keyword, name, ranges = \
                        line.replace(',', ' ').strip().split(None, 2)
                    ranges = ranges.split()
                    values = []
                    for range in ranges:
                        if not range:
                            continue
                        if range.count(':') == 0:
                            values.append(float(range))
                        elif range.count(':') == 1:
                            start, end = range.split(':')
                            start = float(start) if start else None
                            end = float(end) if end else None
                            if start is None:
                                values += list(numpy.arange(end))
                            else:
                                values += list(numpy.arange(start, end))
                        elif range.count(':') == 2:
                            start, end, step = range.split(':')
                            start = float(start) if start else 0
                            end = float(end) if end else None
                            step = float(step) if step else None
                            values += list(numpy.arange(start, end, step))
                        else:
                            conf_syntax_error(filename, lind)

                    # check if already specified
                    if name in conf['pspaces'][-1]['values']:
                        print(f'pspace: {filename}:{lind + 1}: values for parameter "{name}" ' +
                              ' already specified in this context', file=sys.stderr)
                        sys.exit(1)

                    conf['pspaces'][-1]['values'][name] = values

                # parse target accuracy
                elif line.strip().split(None, 1)[0] == 'ACC':
                    try:
                        words = line.strip().split()
                        #if len(words) == 2:
                        keyword, acc = words
                        #op = '<'
                        #elif len(words) == 3:
                        #keyword, op, acc = words

                        # convert value
                        if acc.endswith('%'):
                            acc = float(acc[:-1]) / 100
                        elif acc.endswith('ppm'):
                            acc = float(acc[:-3]) / 1e6
                        elif acc.endswith('ppb'):
                            acc = float(acc[:-3]) / 1e9
                        else:
                            acc = float(acc)
                        #if float(acc) < 1:
                        #else:
                            #acc = int(acc)
                    except:
                        conf_syntax_error(filename, lind)

                    # check if value is positive
                    # not anymore! ACC can be any user-specified number that
                    # serves as an abort criterion
                    #if acc <= 0:
                        #print(f'pspace: {filename}:{lind+1}: ACC must be positive float', file=sys.stderr)
                        #sys.exit(1)

                    # check if already specified
                    if conf['pspaces'][-1]['acc'] is not None:
                        print(f'pspace: {filename}:{lind + 1}: ACC already specified in this context', file=sys.stderr)
                        sys.exit(1)

                    # check operator
                    #if op not in ('<', '>', '<=', '>=', '==', '!='):
                        #print(f'pspace: {filename}:{lind + 1}: bad operator', file=sys.stderr)
                        #sys.exit(1)

                    conf['pspaces'][-1]['acc'] = acc
                    #conf['pspaces'][-1]['op']  = op

            else:
                raise ValueError('unknown context (definitely a bug, please report)')

    # parsing finished, but make a few extra checks here
    # check if undecleared parameters have been used in some parameter space
    for pspace in conf['pspaces']:
        for pname in pspace['values']:
            if pname not in conf['pnames']:
                print(f'pspace: {filename}: parameter "{pname}" undecleared', file=sys.stderr)
                sys.exit(1)

    ## warn about decleared but unused parameters
    #for pname in conf['pnames']:
        #found = False
        #for pspace in conf['pspaces']:
            #if pname in pspace['values']:
                #found = True
                #break
        #if found:
            #continue
        #print 'pspace: %s: warning: parameter "%s" decleared but never used' \
            #% (filename, pname)

    # check if a target accuracy is specified for every parameter space
    for pspace in conf['pspaces']:
        if pspace['acc'] is None:
            print(f'pspace: {filename}: missing ACC in PSPACE context', file=sys.stderr)
            sys.exit(1)

    # check if every parameter has been used in each parameter space
    for pspace in conf['pspaces']:
        for pname in conf['pnames']:
            if not pname in pspace['values']:
                print('pspace: {filename}: parameter "{pname}" missing in PSPACE context', file=sys.stderr)
                sys.exit(1)

    # check if any command or filename templates are missing
    if not conf['CMD_ACC']:
        print(f'pspace: {filename}: missing CMD_ACC specification', file=sys.stderr)
        sys.exit(1)
    if not conf['CMD_EXEC']:
        print(f'pspace: {filename}: missing CMD_EXEC specification', file=sys.stderr)
        sys.exit(1)
    if not conf['CMD_FILE']:
        print(f'pspace: {filename}: missing CMD_FILE specification', file=sys.stderr)
        sys.exit(1)
    if not conf['CMD_CHECKFILE']:
        print(f'pspace: {filename}: missing CMD_CHECKFILE specification' % filename, file=sys.stderr)
        sys.exit(1)
    if not conf['DATAFILE']:
        print(f'pspace: {filename}: missing DATAFILE specification', file=sys.stderr)
        sys.exit(1)
    if not conf['WORKDIR']:
        conf['WORKDIR'] = os.path.expanduser('~')
        #print(f'pspace: {filename}: missing WORKDIR specification', file=sys.stderr)
        #sys.exit(1)
    if not conf['CMD_ACC_OP']:
        conf['CMD_ACC_OP'] = '<='

    # return data structure holding the configuration information
    return conf


def conf_syntax_error(filename, line_index):
    """Exit on syntax error, providing the filename of the configuration file
    and the line number *line_index*."""
    #raise
    print(f'pspace: {filename}:{line_index + 1}: syntax error', file=sys.stderr)
    sys.exit(1)


def printcols(strings, ret=False):
    """Print the strings in the given list *strings* column-wise (similar to
    the Unix shell program *ls*), respecting the width of the terminal window.
    If *ret* is *True*, return the resulting string instead of printing it to
    *stdout*."""
    if len(strings) == 0:
        return
    numstr = len(strings)
    cols = get_cols()
    maxwidth = max([len(remove_ansi_colors(s)) for s in strings])
    numcols = cols/(maxwidth+2)
    numrows = int(ceil(1.*numstr/numcols))

    # print the list
    result = ''
    for rind in range(numrows):
        for cind in range(numcols):
            sind = cind*numrows+rind
            if sind < numstr:
                result += strings[sind] + \
                    ' '*(maxwidth-len(remove_ansi_colors(strings[sind]))+2)
        result += '\n'

    # return or print result
    if ret:
        return result.rstrip()
    else:
        print(result.rstrip())


def remove_ansi_colors(string):
    """Remove all ANSI color escape sequences from a string."""
    if not isinstance(string, str):
        raise TypeError('string expected')
    while True:
        try:
            start = string.index('\033[')
        except ValueError:
            return string
        try:
            end = string.index('m', start)+1
        except ValueError:
            return string
        string = string[:start]+string[end:]


def ceil(x):
    """Return the ceiling of *x*. This exists purely as a substitute for
    *numpy.ceil*, to avoid the dependency on the *numpy* module."""
    if int(x) == x or x <= 0:
        return int(x)
    else:
        return int(x)+1


def get_cols():
    """Try to get the width of the terminal window (will only work on Unix
    systems). If failing, return standard width (80 columns)."""
    try:
        return int(subprocess.getoutput('tput cols'))
    except ValueError:
        # return default width
        return 80


def splits(string, seps=[]):
    """Return a list of the words in the given string, using the list of
    strings *seps* as delimiter strings. A *None* value in *seps* separates the
    string by whitespace of any length"""
    if isinstance(seps, str):
        seps = [seps]
    if len(seps) == 0:
        return string.split()
    parts = string.split(seps[0])
    for sep in seps[1:]:
        newparts = []
        for part in parts:
            newparts += part.split(sep)
        parts = newparts
    return parts


def compare(val1, val2, op):
    """Compare two values using the given operator, which has to be one of the
    strings "<", ">", "<=", ">=", "==", "!="."""
    if op == '<':
        return val1 < val2
    elif op == '>':
        return val1 > val2
    elif op == '<=':
        return val1 <= val2
    elif op == '>=':
        return val1 >= val2
    elif op == '==':
        return val1 == val2
    elif op == '!=':
        return val1 != val2
    else:
        print(f'pspace: unknown operator "{op}"', file=sys.stderr)
        sys.exit(1)


#==============#
# Main program #
#==============#


# map commands (second element of sys.argv) to functions
_cmd2func = {
    'create':    create,      'c': create,
    'submit':    submit,      's': submit,
    'delete':    delete,      'd': delete,
    'info':      info,        'i': info,
    'list':      jlist,       'l': jlist,
    'filenames': fnames,      'f': fnames,
    'cardin':    cardinality, 'n': cardinality,
    'purge':     purge,       'p': purge,
    'users':     users,       'u': users,
    'queues':    queues,      'q': queues
    #'faulty':    faulty,      'y': faulty
}


def call():
    """Call the main program. This function is called when the program is executed from the
    command line."""

    # return words for custom tab completion
    if len(sys.argv) == 2 and sys.argv[1] == '--comp-words':
        keys = sorted(_cmd2func.keys())
        filtered_keys = []
        for key in keys:
            if len(key) > 1:
                filtered_keys.append(key)
        print(' '.join(filtered_keys))
        sys.exit(0)

    # start GUI
    #if len(sys.argv) == 2 and sys.argv[1] == '--gui':
        #sys.exit(start_gui())

    # to enable custom tab completion, add the following lines to your .bashrc
    # (see http://aplawrence.com/Unix/customtab.html#ixzz27bkFS2Y0):
    #pspacewords=$(pspace --comp-words)
    #_pspace()
    #{
        #local curw
        #COMPREPLY=()
        #curw=${COMP_WORDS[COMP_CWORD]}
        #if [ $COMP_CWORD == 1 ]
        #then
            #COMPREPLY=($(compgen -W '$pspacewords' -- $curw))
        #else
            #COMPREPLY=($(compgen -A file -- $curw))
        #fi
        #return 0
    #}
    #complete -F _pspace -o dirnames pspace

    if len(sys.argv) == 1 or sys.argv[1] in ('-?', '--help'):
        # display help
        cmds = {}
        for cmd, func in _cmd2func.items():
            func = func.__name__
            if func not in cmds:
                cmds[func] = {'longs': [], 'shorts': []}
            if len(cmd) <= 1:
                cmds[func]['shorts'].append(cmd)
            else:
                cmds[func]['longs'].append(cmd)

        keys = sorted(cmds.keys())
        cmdstrings = []
        for key in keys:
            cmd = cmds[key]
            cmdstring = ''
            if len(cmd['longs']) != 0:
                cmdstring += cmd['longs'][0]
                if len(cmd['shorts']) != 0:
                    cmdstring += ' ('
                    cmdstring += ', '.join(short for short in cmd['shorts'])
                    cmdstring += ')'
            else:
                cmdstring += ', '.join(short for short in cmd['shorts'])
            cmdstrings.append(cmdstring)

        print(__doc__)
        print()
        print('Available commands (with shortcuts):')
        printcols(cmdstrings)
        print()
        print('To get help to a specific command, use "--help", e.g. "pspace cardin --help"')
    else:
        # execute command
        try:
            func = _cmd2func[sys.argv[1]]
        except KeyError:
            print(f'{sys.argv[1]}: command not found. Type "pspace --help" for a list of pspace commands', file=sys.stderr)
            sys.exit(1)
        func(*sys.argv[2:])
    sys.exit(0)


if __name__ == '__main__':
    call()
    sys.exit(0)
