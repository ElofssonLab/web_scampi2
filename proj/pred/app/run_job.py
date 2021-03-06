#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Description: run job

# Derived from topcons2_workflow_run_job.py on 2015-05-27
# how to create md5
# import hashlib
# md5_key = hashlib.md5(string).hexdigest()
# subfolder = md5_key[:2]

import os
import sys
import time
from libpredweb import myfunc
from libpredweb import webserver_common as webcom
import glob
import hashlib
import shutil
import sqlite3
from datetime import datetime
from dateutil import parser as dtparser
from pytz import timezone
progname =  os.path.basename(sys.argv[0])
wspace = ''.join([" "]*len(progname))
rundir = os.path.dirname(os.path.realpath(__file__))
suq_basedir = "/tmp"

blastdir = "%s/%s"%(rundir, "soft/blast/blast-2.2.26")
os.environ['SCAMPI_DIR'] = "/server/scampi"
os.environ['MODHMM_BIN'] = "/server/modhmm/bin"
os.environ['BLASTMAT'] = "%s/data"%(blastdir)
os.environ['BLASTBIN'] = "%s/bin"%(blastdir)
os.environ['BLASTDB'] = "%s/%s"%(rundir, "soft/blastdb")
blastdb = "%s/%s"%(os.environ['BLASTDB'], "uniref90.fasta" )
#blastdb = "/data3/data/blastdb/swissprot"
runscript_single = "%s/%s"%(rundir, "soft/scampi2/bin/scampi/SCAMPI_run.pl")
runscript_msa = "%s/%s"%(rundir, "soft/scampi2/bin/scampi-msa/run_SCAMPI_multi.pl")

basedir = os.path.realpath("%s/.."%(rundir)) # path of the application, i.e. pred/
path_result = "%s/static/result"%(basedir)
db_cache_SCAMPI2MSA = "%s/cache_msa.sqlite3"%(path_result)
dbmsa_tablename = "scampi2msa"

contact_email = "nanjiang.shu@scilifelab.se"
vip_user_list = [
        "nanjiang.shu@scilifelab.se"
        ]
TZ = "Europe/Stockholm"
os.environ['TZ'] = TZ
FORMAT_DATETIME = "%Y-%m-%d %H:%M:%S %Z"

# note that here the url should be without http://

usage_short="""
Usage: %s seqfile_in_fasta 
       %s -jobid JOBID -outpath DIR -tmpdir DIR
       %s -email EMAIL -baseurl BASE_WWW_URL
       %s -apptype -only-get-cache [-force]
"""%(progname, wspace, wspace, wspace)

usage_ext="""\
Description:
    run job

OPTIONS:
  -force            Do not use cahced result
  -only-get-cache   Only get the cached results, this will be run on the front-end
  -h, --help        Print this help message and exit

Created 2015-07-07, updated 2017-09-16, Nanjiang Shu
"""
usage_exp="""
Examples:
    %s /data3/tmp/tmp_dkgSD/query.fa -outpath /data3/result/rst_mXLDGD -tmpdir /data3/tmp/tmp_dkgSD
"""%(progname)

def PrintHelp(fpout=sys.stdout):#{{{
    print(usage_short, file=fpout)
    print(usage_ext, file=fpout)
    print(usage_exp, file=fpout)#}}}

def RunJob_msa(infile, outpath, tmpdir, email, jobid, g_params):#{{{
    all_begin_time = time.time()

    rootname = os.path.basename(os.path.splitext(infile)[0])
    runjob_errfile = "%s/runjob.err"%(outpath)
    runjob_logfile = "%s/runjob.log"%(outpath)
    starttagfile   = "%s/runjob.start"%(outpath)
    finishtagfile = "%s/runjob.finish"%(outpath)
    failtagfile = "%s/runjob.failed"%(outpath)
    rmsg = ""
    qdinit_start_tagfile = "%s/runjob.qdinit.start"%(outpath)

    # if the daemon starts to process the job before the run_job.py running 
    # in the local queue, skip it
    if os.path.exists(qdinit_start_tagfile):
        return 0

    resultpathname = jobid

    outpath_result = "%s/%s"%(outpath, resultpathname)
    tmp_outpath_result = "%s/%s"%(tmpdir, resultpathname)

    tarball = "%s.tar.gz"%(resultpathname)
    zipfile = "%s.zip"%(resultpathname)
    tarball_fullpath = "%s.tar.gz"%(outpath_result)
    zipfile_fullpath = "%s.zip"%(outpath_result)
    resultfile_text = "%s/%s"%(outpath_result, "query.result.txt")
    mapfile = "%s/seqid_index_map.txt"%(outpath_result)
    finished_seq_file = "%s/finished_seqs.txt"%(outpath_result)
    finished_idx_file = "%s/finished_seqindex.txt"%(outpath)

    for folder in [outpath_result, tmp_outpath_result]:
        try:
            os.makedirs(folder)
        except OSError:
            msg = "Failed to create folder %s"%(folder)
            myfunc.WriteFile(msg+"\n", gen_errfile, "a")
            return 1


    try:
        open(finished_seq_file, 'w').close()
    except:
        pass
#first getting result from caches
# ==================================
    maplist = []
    toRunDict = {}
    hdl = myfunc.ReadFastaByBlock(infile, method_seqid=0, method_seq=0)
    if hdl.failure:
        isOK = False
    else:
        webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)
        cnt = 0
        origpath = os.getcwd()
        con = sqlite3.connect(db_cache_SCAMPI2MSA)
        with con:
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS %s
                (
                    md5 VARCHAR(100),
                    seq VARCHAR(30000),
                    top VARCHAR(30000),
                    PRIMARY KEY (md5)
                )"""%(dbmsa_tablename))
            recordList = hdl.readseq()
            while recordList != None:
                for rd in recordList:
                    isSkip = False
                    if not g_params['isForceRun']:
                        md5_key = hashlib.md5(rd.seq.encode('utf-8')).hexdigest()
                        cmd =  "SELECT md5, seq, top FROM %s WHERE md5 =  \"%s\""%(
                                dbmsa_tablename, md5_key)
                        cur.execute(cmd)
                        rows = cur.fetchall()
                        for row in rows:
                            top = row[2]
                            numTM = myfunc.CountTM(top)
                            # info_finish has 8 items
                            info_finish = [ "seq_%d"%cnt, str(len(rd.seq)), str(numTM),
                                    "cached", str(0.0), rd.description, rd.seq, top]
                            myfunc.WriteFile("\t".join(info_finish)+"\n",
                                    finished_seq_file, "a", isFlush=True)
                            myfunc.WriteFile("%d\n"%(cnt), finished_idx_file, "a", isFlush=True)
                            isSkip = True

                    if not isSkip:
                        # first try to delete the outfolder if exists
                        origIndex = cnt
                        numTM = 0
                        toRunDict[origIndex] = [rd.seq, numTM, rd.description] #init value for numTM is 0
                    cnt += 1
                recordList = hdl.readseq()
            hdl.close()


    if not g_params['isOnlyGetCache']:
        torun_all_seqfile = "%s/%s"%(tmp_outpath_result, "query.torun.fa")
        dumplist = []
        for key in toRunDict:
            top = toRunDict[key][0]
            dumplist.append(">%s\n%s"%(str(key), top))
        myfunc.WriteFile("\n".join(dumplist)+"\n", torun_all_seqfile, "w")
        del dumplist
        sortedlist = sorted(list(toRunDict.items()), key=lambda x:x[1][1], reverse=True)
        #format of sortedlist [(origIndex: [seq, numTM, description]), ...]
        # submit sequences one by one to the workflow according to orders in
        # sortedlist
        for item in sortedlist:
            origIndex = item[0]
            seq = item[1][0]
            description = item[1][2]

            outpath_this_seq = "%s/%s"%(outpath_result, "seq_%d"%origIndex)
            tmp_outpath_this_seq = "%s/%s"%(tmp_outpath_result, "seq_%d"%(0))
            if os.path.exists(tmp_outpath_this_seq):
                try:
                    shutil.rmtree(tmp_outpath_this_seq)
                except OSError:
                    pass
            try:
                os.makedirs(tmp_outpath_this_seq)
            except OSError:
                g_params['runjob_err'].append("Failed to create the tmp_outpath_this_seq %s"%(tmp_outpath_this_seq))
                continue

            seqfile_this_seq = "%s/%s"%(tmp_outpath_result, "query_%d.fa"%(origIndex))
            seqcontent = ">%d\n%s\n"%(origIndex, seq)
            myfunc.WriteFile(seqcontent, seqfile_this_seq, "w")

            if not os.path.exists(seqfile_this_seq):
                g_params['runjob_err'].append("failed to generate seq index %d"%(origIndex))
                continue

            if not os.path.exists("%s/seq.fa"%(tmp_outpath_this_seq)):
                try:
                    shutil.copyfile(seqfile_this_seq, "%s/seq.fa"%(tmp_outpath_this_seq))
                except OSError:
                    pass

            numCPU = 4
            outtopfile = "%s/query.top"%(tmp_outpath_this_seq)
            cmd = [runscript_msa, seqfile_this_seq, outtopfile, blastdir, blastdb]
            (t_success, runtime_in_sec) = webcom.RunCmd(cmd, runjob_logfile, runjob_errfile, verbose=True)

            if os.path.exists(tmp_outpath_this_seq):
                cmd = ["mv","-f", tmp_outpath_this_seq, outpath_this_seq]
                (isCmdSuccess, t_runtime) = webcom.RunCmd(cmd, runjob_logfile, runjob_errfile, verbose=True)

                if isCmdSuccess:
                    runtime = runtime_in_sec #in seconds
                    predfile = "%s/query.top"%(outpath_this_seq)
                    (seqid, seqanno, top) = myfunc.ReadSingleFasta(predfile)
                    numTM = myfunc.CountTM(top)
                    # info_finish has 8 items
                    info_finish = [ "seq_%d"%origIndex, str(len(seq)),
                            str(numTM), "newrun", str(runtime), description, seq, top]
                    myfunc.WriteFile("\t".join(info_finish)+"\n",
                            finished_seq_file, "a", isFlush=True)

    all_end_time = time.time()
    all_runtime_in_sec = all_end_time - all_begin_time

    if len(g_params['runjob_log']) > 0 :
        rt_msg = myfunc.WriteFile("\n".join(g_params['runjob_log'])+"\n", runjob_logfile, "a")
        if rt_msg:
            g_params['runjob_err'].append(rt_msg)

    if not g_params['isOnlyGetCache'] or len(toRunDict) == 0:
        if os.path.exists(finished_seq_file):
            webcom.WriteDateTimeTagFile(finishtagfile, runjob_logfile, runjob_errfile)

# now write the text output to a single file
        dumped_resultfile = "%s/%s"%(outpath_result, "query.top")
        statfile = "%s/%s"%(outpath_result, "stat.txt")
        webcom.WriteSCAMPI2MSATextResultFile(dumped_resultfile, outpath_result, maplist,
                all_runtime_in_sec, g_params['base_www_url'], statfile=statfile)


        # now making zip instead (for windows users)
        pwd = os.getcwd()
        os.chdir(outpath)
        cmd = ["zip", "-rq", zipfile, resultpathname]
        webcom.RunCmd(cmd, runjob_logfile, runjob_errfile)
        os.chdir(pwd)


        isSuccess = False
        if (os.path.exists(finishtagfile) and os.path.exists(zipfile_fullpath)):
            isSuccess = True
            # delete the tmpdir if succeeded
            shutil.rmtree(tmpdir) #DEBUG, keep tmpdir
        else:
            isSuccess = False
            webcom.WriteDateTimeTagFile(failtagfile, runjob_logfile, runjob_errfile)

        finish_status = "" #["success", "failed", "partly_failed"]
        if isSuccess:
            finish_status = "success"
        else:
            finish_status = "failed"

# send the result to email
# do not sendmail at the cloud VM
        if webcom.IsFrontEndNode(g_params['base_www_url']) and myfunc.IsValidEmailAddress(email):
            webcom.SendEmail_on_finish(jobid, g_params['base_www_url'],
                    finish_status, name_server="SCAMPI2-msa", from_email="no-reply.SCAMPI@bioinfo.se",
                    to_email=email, contact_email=contact_email,
                    logfile=runjob_logfile, errfile=runjob_errfile)
    return 0

#}}}
def RunJob_single(infile, outpath, tmpdir, email, jobid, g_params):#{{{
    all_begin_time = time.time()

    rootname = os.path.basename(os.path.splitext(infile)[0])
    starttagfile   = "%s/runjob.start"%(outpath)
    finishtagfile = "%s/runjob.finish"%(outpath)
    failtagfile = "%s/runjob.failed"%(outpath)
    runjob_errfile = "%s/runjob.err"%(outpath)
    runjob_logfile = "%s/runjob.log"%(outpath)
    rmsg = ""

    resultpathname = jobid

    outpath_result = "%s/%s"%(outpath, resultpathname)
    tmp_outpath_result = "%s/%s"%(tmpdir, resultpathname)

    tarball = "%s.tar.gz"%(resultpathname)
    zipfile = "%s.zip"%(resultpathname)
    tarball_fullpath = "%s.tar.gz"%(outpath_result)
    zipfile_fullpath = "%s.zip"%(outpath_result)
    resultfile_text = "%s/%s"%(outpath_result, "query.result.txt")
    outfile = "%s/%s"%(outpath_result, "query.top")

    isOK = True
    try:
        os.makedirs(tmp_outpath_result)
        isOK = True
    except OSError:
        msg = "Failed to create folder %s"%(tmp_outpath_result)
        myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
        isOK = False
        pass
    tmp_outfile = "%s/%s"%(tmp_outpath_result, "query.top")

    try:
        os.makedirs(outpath_result)
        isOK = True
    except OSError:
        msg = "Failed to create folder %s"%(outpath_result)
        myfunc.WriteFile(msg+"\n", runjob_errfile, "a")
        isOK = False
        pass


    if isOK:
        webcom.WriteDateTimeTagFile(starttagfile, runjob_logfile, runjob_errfile)

        cmd = [runscript_single, infile,  tmp_outfile]
        (t_success, runtime_in_sec) = webcom.RunCmd(cmd, runjob_logfile, runjob_errfile, verbose=True)

        if os.path.exists(tmp_outfile):
            cmd = ["mv","-f", tmp_outfile, outfile]
            (isCmdSuccess, t_runtime) = webcom.RunCmd(cmd, runjob_logfile, runjob_errfile)
            if isCmdSuccess:
                runtime = runtime_in_sec #in seconds

        if len(g_params['runjob_log']) > 0 :
            rt_msg = myfunc.WriteFile("\n".join(g_params['runjob_log'])+"\n", runjob_logfile, "a")
            if rt_msg:
                g_params['runjob_err'].append(rt_msg)

        if os.path.exists(outfile):
            webcom.WriteDateTimeTagFile(finishtagfile, runjob_logfile, runjob_errfile)


    isSuccess = False
    if (os.path.exists(finishtagfile) and os.path.exists(outfile)):
        isSuccess = True
        finish_status = "success"
    else:
        isSuccess = False
        finish_status = "failed"
        webcom.WriteDateTimeTagFile(failtagfile, runjob_logfile, runjob_errfile)

# send the result to email
# do not sendmail at the cloud VM
    if webcom.IsFrontEndNode(g_params['base_www_url']) and myfunc.IsValidEmailAddress(email):
        webcom.SendEmail_on_finish(jobid, g_params['base_www_url'],
                finish_status, name_server="SCAMPI2-single", from_email="no-reply.SCAMPI@bioinfo.se",
                to_email=email, contact_email=contact_email,
                logfile=runjob_logfile, errfile=runjob_errfile)
    return 0
#}}}
def main(g_params):#{{{
    argv = sys.argv
    numArgv = len(argv)
    if numArgv < 2:
        PrintHelp()
        return 1

    outpath = ""
    infile = ""
    tmpdir = ""
    email = ""
    jobid = ""

    i = 1
    isNonOptionArg=False
    while i < numArgv:
        if isNonOptionArg == True:
            infile = argv[i]
            isNonOptionArg = False
            i += 1
        elif argv[i] == "--":
            isNonOptionArg = True
            i += 1
        elif argv[i][0] == "-":
            if argv[i] in ["-h", "--help"]:
                PrintHelp()
                return 1
            elif argv[i] in ["-outpath", "--outpath"]:
                (outpath, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-apptype", "--apptype"]:
                (g_params['app_type'], i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-tmpdir", "--tmpdir"] :
                (tmpdir, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-jobid", "--jobid"] :
                (jobid, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-baseurl", "--baseurl"] :
                (g_params['base_www_url'], i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-email", "--email"] :
                (email, i) = myfunc.my_getopt_str(argv, i)
            elif argv[i] in ["-q", "--q"]:
                g_params['isQuiet'] = True
                i += 1
            elif argv[i] in ["-force", "--force"]:
                g_params['isForceRun'] = True
                i += 1
            elif argv[i] in ["-only-get-cache", "--only-get-cache"]:
                g_params['isOnlyGetCache'] = True
                i += 1
            else:
                print("Error! Wrong argument:", argv[i], file=sys.stderr)
                return 1
        else:
            infile = argv[i]
            i += 1

    if jobid == "":
        print("%s: jobid not set. exit"%(sys.argv[0]), file=sys.stderr)
        return 1

    if myfunc.checkfile(infile, "infile") != 0:
        return 1
    if outpath == "":
        print("outpath not set. exit", file=sys.stderr)
        return 1
    elif not os.path.exists(outpath):
        try:
            os.makedirs(outpath)
        except Exception as e:
            print(e, file=sys.stderr)
            return 1
    if tmpdir == "":
        print("tmpdir not set. exit", file=sys.stderr)
        return 1
    elif not os.path.exists(tmpdir):
        try:
            os.makedirs(tmpdir)
        except Exception as e:
            print(e, file=sys.stderr)
            return 1

    numseq = myfunc.CountFastaSeq(infile)
    g_params['debugfile'] = "%s/debug.log"%(outpath)
    if g_params['app_type'] == "SCAMPI-single":
        return RunJob_single(infile, outpath, tmpdir, email, jobid, g_params)
    else:
        return RunJob_msa(infile, outpath, tmpdir, email, jobid, g_params)
#}}}

def InitGlobalParameter():#{{{
    g_params = {}
    g_params['isQuiet'] = True
    g_params['runjob_log'] = []
    g_params['runjob_err'] = []
    g_params['isForceRun'] = False
    g_params['isOnlyGetCache'] = False
    g_params['base_www_url'] = ""
    g_params['app_type'] = "SCAMPI-single"
    return g_params
#}}}
if __name__ == '__main__' :
    g_params = InitGlobalParameter()
    sys.exit(main(g_params))
