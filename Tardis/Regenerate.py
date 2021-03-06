# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Tardis: A Backup System
# Copyright 2013-2016, Eric Koldinger, All Rights Reserved.
# kolding@washington.edu
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import os
import os.path
import stat
import sys
import argparse
import logging
import time
import base64
import json
import parsedatetime
import xattr
import posix1e

import Tardis
import TardisDB
import Regenerator
import Util
import Config

logger  = None
exceptionLogger = None
crypt = None
OW_NEVER = 0
OW_ALWAYS = 1
OW_NEWER = 2
OW_OLDER = 3

overwriteNames = { 'never': OW_NEVER, 'always': OW_ALWAYS, 'newer': OW_NEWER, 'older': OW_OLDER }
owMode = OW_NEVER

errors = 0

tardis = None
args = None

fsencoding = sys.getfilesystemencoding()
reload(sys)
sys.setdefaultencoding(fsencoding)

def checkOverwrite(name, info):
    if os.path.exists(name):
        if owMode == OW_NEVER:
            return False
        elif owMode == OW_ALWAYS:
            return True
        else:
            s = os.lstat(name)
            if s.st_mtime < info['mtime']:
                # Current version is older
                return True if owMode == OW_NEWER else False
            else:
                # Current version is newer
                return True if owMode == OW_OLDER else False
    else:
        return True

def doAuthenticate(outname, checksum, digest):
    """
    Check that the recorded checksum of the file, and the digest of the generated file match.
    Perform the expected action if they don't.  Return the name of the file that's being generated.
    """
    logger.debug("File: %s Expected Hash: %s Hash: %s", outname, checksum, digest)
    # should use hmac.compare_digest() here, but it's not working for some reason.  Probably different types
    if checksum != digest:
        if outname:
            if args.authfailaction == 'keep':
                action = ''
                target = outname
            elif args.authfailaction == 'rename':
                target = outname + '-CORRUPT-' + str(digest)
                action = 'Renaming to ' + target + '.'
                try:
                    os.rename(outname, target)
                except:
                    action = "Unable to rename to " + target + ".  File saved as " + outname + "."
            elif args.authfailaction == 'delete':
                action = 'Deleting.'
                os.unlink(outname)
                target = None
        else:
            target = None
            action = ''
        if outname is None:
            outname = ''
        logger.critical("File %s did not authenticate.  Expected: %s.  Got: %s.  %s",
                        outname, checksum, digest, action)
        return target
    else:
        return outname

def notSame(a, b, string):
    if a == b:
        return ''
    else:
        return string

def recoverObject(regenerator, info, bset, outputdir, path, linkDB, name=None, authenticate=True):
    """
    Main recovery routine.  Recover an object, based on the info object, and put it in outputdir.
    """
    retCode = 0
    outname = None
    skip = False
    hasher = None
    try:
        if info:
            realname = info['name']
            if args.crypt and crypt:
                realname = crypt.decryptFilename(realname)

            if name:
                # This should only happen only one file specified.
                outname = name
            elif outputdir:
                outname = os.path.abspath(os.path.join(outputdir, realname))

            if outname and not checkOverwrite(outname, info):
                skip = True
                try:
                    logger.warning("Skipping existing file: %s %s", Util.shortPath(path), notSame(path, outname, '(' + Util.shortPath(outname) + ')'))
                except Exception:
                    pass

            # First, determine if we're in a linking situation
            if linkDB is not None and info['nlinks'] > 1 and not info['dir']:
                key = (info['inode'], info['device'])
                if key in linkDB:
                    logger.info("Linking %s to %s", outname, linkDB[key])
                    os.link(linkDB[key], outname)
                    skip = True
                else:
                    linkDB[key] = outname

            # If it's a directory, create the directory, and recursively process it
            if info['dir']:
                if not outname:
                    #logger.error("Cannot regenerate directory %s without outputdir specified", path)
                    raise Exception("Cannot regenerate directory %s without outputdir specified" % (path))

                try:
                    logger.info("Processing directory %s", Util.shortPath(path))
                except Exception:
                    pass

                contents = list(tardis.readDirectory((info['inode'], info['device']), bset))

                # Make sure an output directory is specified (really only useful at the top level)
                if not os.path.exists(outname):
                    os.mkdir(outname)

                dirInode = (info['inode'], info['device'])
                # For each file in the directory, regenerate it.
                for i in contents:
                    name = i['name']
                    # Get the Info
                    childInfo = tardis.getFileInfoByName(name, dirInode, bset)

                    # Decrypt filename, and make it UTF-8.
                    if args.crypt and crypt:
                        name = unicode(crypt.decryptFilename(name))
                    else:
                        name = unicode(name, 'utf8')

                    # Recurse into the child, if it exists.
                    if childInfo:
                        try:
                            if args.recurse or not childInfo['dir']:
                                recoverObject(regenerator, childInfo, bset, outname, os.path.join(path, name), linkDB, authenticate=authenticate)
                        except Exception as e:
                            logger.error("Could not recover %s in %s", name, path)
                            exceptionLogger.log(e)
                    else:
                        retCode += 1
            elif not skip:
                myname = outname if outname else "stdout"
                logger.info("Recovering file %s %s", Util.shortPath(path), notSame(path, myname, " => " + Util.shortPath(myname)))

                checksum = info['checksum']
                i = regenerator.recoverChecksum(checksum, authenticate)

                if i:
                    if authenticate:
                        hasher = Util.getHash(crypt)

                    if info['link']:
                        # read and make a link
                        i.seek(0)
                        x = i.read(16 * 1024)
                        if outname:
                            os.symlink(x, outname)
                        else:
                            logger.warning("No name specified for link: %s", x)
                        if hasher:
                            hasher.update(x)
                    else:
                        if outname:
                            # Generate an output name
                            logger.debug("Writing output to %s", outname)
                            output = file(outname,  "wb")
                        else:
                            output = sys.stdout
                        try:
                            x = i.read(16 * 1024)
                            while x:
                                output.write(x)
                                if hasher:
                                    hasher.update(x)
                                x = i.read(16 * 1024)
                        except Exception as e:
                            logger.error("Unable to read file: {}: {}".format(i, repr(e)))
                            raise
                        finally:
                            i.close()
                            if output is not sys.stdout:
                                output.close()

                        if authenticate:
                            outname = doAuthenticate(outname, checksum, hasher.hexdigest())

            if outname and args.setperm:
                try:
                    logger.debug("Setting permissions on %s to %o", outname, info['mode'])
                    os.chmod(outname, info['mode'])
                except Exception as e:
                    logger.warning("Unable to set permissions for %s", outname)
                try:
                    # Change the group, then the owner.
                    # Change the group first, as only root can change owner, and that might fail.
                    os.chown(outname, -1, info['gid'])
                    os.chown(outname, info['uid'], -1)
                except Exception as e:
                    logger.warning("Unable to set owner and group of %s", outname)
            if outname and args.setattrs and 'attr' in info and info['attr']:
                try:
                    f = regenerator.recoverChecksum(info['attr'], authenticate)
                    xattrs = json.loads(f.read())
                    x = xattr.xattr(outname)
                    for attr in xattrs.keys():
                        value = base64.b64decode(xattrs[attr])
                        try:
                            x.set(attr, value)
                        except IOError:
                            logger.warning("Unable to set extended attribute %s on %s", attr, outname)
                except Exception as e:
                    logger.warning("Unable to process extended attributes for %s", outname)
            if outname and args.setacl and 'acl' in info and info['acl']:
                try:
                    f = regenerator.recoverChecksum(info['acl'], authenticate)
                    acl = json.loads(f.read())
                    a = posix1e.ACL(text=acl)
                    a.applyto(outname)
                except Exception as e:
                    logger.warning("Unable to process extended attributes for %s", outname)
    except Exception as e:
        logger.error("Recovery of %s failed. %s", outname, e)
        exceptionLogger.log(e)
        retCode += 1

    return retCode

def setupPermissionChecks():
    uid = os.getuid()
    groups = os.getgroups()

    if uid == 0:
        return None     # If super-user, return None.  Causes no checking to happen.

    # Otherwise, create a closure function which can be used to do checking for each file.
    def checkPermission(pUid, pGid, mode):
        if stat.S_ISDIR(mode):
            if (uid == pUid) and (stat.S_IRUSR & mode) and (stat.S_IXUSR & mode):
                return True
            elif (pGid in groups) and (stat.S_IRGRP & mode) and (stat.S_IXGRP & mode):
                return True
            elif (stat.S_IROTH & mode) and (stat.S_IXOTH & mode):
                return True
        else:
            if (uid == pUid) and (stat.S_IRUSR & mode):
                return True
            elif (pGid in groups) and (stat.S_IRGRP & mode):
                return True
            elif stat.S_IROTH & mode:
                return True
        return False

    # And return the function.
    return checkPermission

def findLastPath(path, reduce):
    logger.debug("findLastPath: %s", path)
    # Search all the sets in backwards order
    bsets = list(tardis.listBackupSets())
    for bset in reversed(bsets):
        logger.debug("Checking for path %s in %s (%d)", path, bset['name'], bset['backupset'])
        tmp = Util.reducePath(tardis, bset['backupset'], os.path.abspath(path), reduce, crypt)
        tmp2 = tmp
        if args.crypt and crypt:
            tmp2 = crypt.encryptPath(tmp)
        info = tardis.getFileInfoByPath(tmp2, bset['backupset'])
        if info:
            logger.debug("Found %s in backupset %s: %s", path, bset['name'], tmp)
            return bset['backupset'], tmp, bset['name']
    return (None, None, None)

def recoverName(cksum):
    names = tardis.getNamesForChecksum(cksum)
    #print names
    if names:
        if args.crypt and crypt:
            names = map(crypt.decryptFilename, names)
        name = names[0]
        if len(names) > 1:
            logger.warning("Multiple (%d) names for checksum %s %s.  Choosing '%s'.", len(names), cksum, map(str, list(names)), name)
        return name
    else:
        logger.error("No name discovered for checksum %s", cksum)
        return cksum

def mkOutputDir(name):
    if os.path.isdir(name):
        return name
    elif os.path.exists(name):
        self.logger.error("%s is not a directory")
    else:
        os.mkdir(name)
        return name

def parseArgs():
    parser = argparse.ArgumentParser(description='List Tardis File Versions', fromfile_prefix_chars='@', formatter_class=Util.HelpFormatter, add_help=False)

    (_, remaining) = Config.parseConfigOptions(parser)
    Config.addCommonOptions(parser)
    Config.addPasswordOptions(parser)

    parser.add_argument("--output", "-o",   dest="output", help="Output file", default=None)
    parser.add_argument("--checksum", "-c", help="Use checksum instead of filename", dest='cksum', action='store_true', default=False)

    bsetgroup = parser.add_mutually_exclusive_group()
    bsetgroup.add_argument("--backup", "-b", help="Backup set to use", dest='backup', default=None)
    bsetgroup.add_argument("--date", "-d",   help="Regenerate as of date", dest='date', default=None)
    bsetgroup.add_argument("--last", "-l",   dest='last', default=False, action='store_true', help="Regenerate the most recent version of the file")

    parser.add_argument('--recurse',        dest='recurse', default=True, action=Util.StoreBoolean, help='Recurse directory trees.  Default: %(default)s')
    parser.add_argument('--recovername',    dest='recovername', default=False, action=Util.StoreBoolean,    help='Recover the name when recovering a checksum.  Default: %(default)s')

    parser.add_argument('--authenticate',    dest='auth', default=True, action=Util.StoreBoolean,    help='Authenticate files while regenerating them.  Default: %(default)s')
    parser.add_argument('--authfail-action', dest='authfailaction', default='rename', choices=['keep', 'rename', 'delete'], help='Action to take for files that do not authenticate.  Default: %(default)s')

    parser.add_argument('--reduce-path', '-R',  dest='reduce',  default=0, const=sys.maxint, type=int, nargs='?',   metavar='N',
                        help='Reduce path by N directories.  No value for "smart" reduction')
    parser.add_argument('--set-times', dest='settime', default=True, action=Util.StoreBoolean,      help='Set file times to match original file. Default: %(default)s')
    parser.add_argument('--set-perms', dest='setperm', default=True, action=Util.StoreBoolean,      help='Set file owner and permisions to match original file. Default: %(default)s')
    parser.add_argument('--set-attrs', dest='setattrs', default=True, action=Util.StoreBoolean,     help='Set file extended attributes to match original file.  May only set attributes in user space. Default: %(default)s')
    parser.add_argument('--set-acl',   dest='setacl', default=True, action=Util.StoreBoolean,       help='Set file access control lists to match the original file. Default: %(default)s')
    parser.add_argument('--overwrite', '-O', dest='overwrite', default='never', const='always', nargs='?',
                        choices=['always', 'newer', 'older', 'never'], help='Mode for handling existing files. Default: %(default)s')

    parser.add_argument('--hardlinks',  dest='hardlinks',   default=True,   action=Util.StoreBoolean,   help='Create hardlinks of multiple copies of same inode created. Default: %(default)s')

    parser.add_argument('--exceptions',         default=False, action=Util.StoreBoolean, dest='exceptions', help="Log full exception data");
    parser.add_argument('--verbose', '-v',      action='count', default=0, dest='verbose', help='Increase the verbosity')
    parser.add_argument('--version',            action='version', version='%(prog)s ' + Tardis.__versionstring__,    help='Show the version')
    parser.add_argument('--help', '-h',         action='help')

    parser.add_argument('files', nargs='+', default=None, help="List of files to regenerate")

    Util.addGenCompletions(parser)

    return parser.parse_args(remaining)

def main():
    global logger, crypt, tardis, args, owMode, exceptionLogger
    args = parseArgs()
    logger = Util.setupLogging(args.verbose, stream=sys.stderr)
    exceptionLogger = Util.ExceptionLogger(logger, args.exceptions)

    try:
        password = Util.getPassword(args.password, args.passwordfile, args.passwordprog, prompt="Password for %s: " % (args.client))
        args.password = None
        (tardis, cache, crypt) = Util.setupDataConnection(args.database, args.client, password, args.keys, args.dbname, args.dbdir)

        r = Regenerator.Regenerator(cache, tardis, crypt=crypt)
    except TardisDB.AuthenticationException as e:
        logger.error("Authentication failed.  Bad password")
        exceptionLogger.log(e)
        sys.exit(1)
    except Exception as e:
        logger.error("Regeneration failed: %s", e)
        sys.exit(1)

    try:
        bset = False

        if args.date:
            cal = parsedatetime.Calendar()
            (then, success) = cal.parse(args.date)
            if success:
                timestamp = time.mktime(then)
                logger.info("Using time: %s", time.asctime(then))
                bsetInfo = tardis.getBackupSetInfoForTime(timestamp)
                if bsetInfo and bsetInfo['backupset'] != 1:
                    bset = bsetInfo['backupset']
                    logger.debug("Using backupset: %s %d", bsetInfo['name'], bsetInfo['backupset'])
                else:
                    logger.critical("No backupset at date: %s (%s)", args.date, time.asctime(then))
                    sys.exit(1)
            else:
                logger.critical("Could not parse date string: %s", args.date)
                sys.exit(1)
        elif args.backup:
            bsetInfo = tardis.getBackupSetInfo(args.backup)
            if bsetInfo:
                bset = bsetInfo['backupset']
            else:
                logger.critical("No backupset at for name: %s", args.backup)
                sys.exit(1)

        outputdir = None
        output    = sys.stdout
        outname   = None
        linkDB    = None

        owMode    = overwriteNames[args.overwrite]

        if args.output:
            if len(args.files) > 1:
                outputdir = mkOutputDir(args.output)
            elif os.path.isdir(args.output):
                outputdir = args.output
            else:
                outname = args.output
        logger.debug("Outputdir: %s  Outname: %s", outputdir, outname)

        if args.hardlinks:
            linkDB = {}

        #if args.cksum and (args.settime or args.setperm):
            #logger.warning("Unable to set time or permissions on files specified by checksum.")

        permChecker = setupPermissionChecks()

        retcode = 0
        hasher = None

        # do the work here
        if args.cksum:
            for i in args.files:
                try:
                    if args.auth:
                        hasher = Util.getHash(crypt)
                    ckname = i
                    if args.recovername:
                        ckname = recoverName(i)
                    f = r.recoverChecksum(i, args.auth)
                    if f:
                    # Generate an output name
                        if outname:
                            # Note, this should ONLY be true if only one file
                            output = file(outname,  "wb")
                        elif outputdir:
                            outname = os.path.join(outputdir, ckname)
                            logger.debug("Writing output to %s", outname)
                            output = file(outname,  "wb")
                        try:
                            x = f.read(64 * 1024)
                            while x:
                                output.write(x)
                                if hasher:
                                    hasher.update(x)
                                x = f.read(64 * 1024)
                        except Exception as e:
                            logger.error("Unable to read file: {}: {}".format(i, repr(e)))
                            raise
                        finally:
                            f.close()
                            if output is not sys.stdout:
                                output.close()
                        if args.auth:
                            logger.debug("Checking authentication")
                            outname = doAuthenticate(outname, i, hasher.hexdigest())

                except TardisDB.AuthenticationException as e:
                    logger.error("Authentication failed.  Bad password")
                    exceptionLogger.log(e)
                    sys.exit(1)
                except Exception as e:
                    logger.error("Could not recover: %s: %s", i, e)
                    exceptionLogger.log(e)
                    retcode += 1

        else: # Not checksum, but acutal pathnames
            for i in args.files:
                try:
                    i = unicode(os.path.abspath(i).decode('utf-8'))
                    logger.info("Processing %s", Util.shortPath(i))
                    path = None
                    f = None
                    if args.last:
                        (bset, path, name) = findLastPath(i, args.reduce)
                        if bset is None:
                            logger.error("Unable to find a latest version of %s", i)
                            raise Exception("Unable to find a latest version of " + i)
                        logger.info("Found %s in backup set %s", i, name)
                    elif args.reduce:
                        path = Util.reducePath(tardis, bset, i, args.reduce, crypt)
                        logger.debug("Reduced path %s to %s", path, i)
                        if not path:
                            logger.error("Unable to find a compute path for %s", i)
                            raise Exception("Unable to compute path for " + i)
                    else:
                        path = i

                    if args.crypt and crypt:
                        actualPath = crypt.encryptPath(path)
                    else:
                        actualPath = path
                    logger.debug("Actual path is %s -- %s", actualPath, bset)
                    info = tardis.getFileInfoByPath(actualPath, bset)
                    if info:
                        retcode += recoverObject(r, info, bset, outputdir, path, linkDB, name=outname, authenticate=args.auth)
                    else:
                        logger.error("Could not recover info for %s", i)
                        retcode += 1
                except TardisDB.AuthenticationException as e:
                    logger.error("Authentication failed.  Bad password")
                    exceptionLogger.log(e)
                    sys.exit(1)
                except Exception as e:
                    logger.error("Could not recover: %s: %s", i, e)
                    exceptionLogger.log(e)
    except KeyboardInterrupt:
        logger.error("Recovery interupted")
    except TardisDB.AuthenticationException as e:
        logger.error("Authentication failed.  Bad password")
        exceptionLogger.log(e)
    except Exception as e:
        logger.error("Regeneration failed: %s", e)
        exceptionLogger.log(e)

    if errors:
        logger.warning("%d files could not be recovered.")

    return retcode

if __name__ == "__main__":
    sys.exit(main())

