# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Tardis: A Backup System
# Copyright 2013-2014, Eric Koldinger, All Rights Reserved.
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

import requests
import logging
import tempfile

import ConnIdLogAdapter

class RemoteDB(object):
    """ Proxy class to retrieve objects via HTTP queries """
    session = None

    def __init__(self, url, host, prevSet=None, extra=None, token=None):
        self.logger=logging.getLogger('Remote')
        self.session = requests.Session()
        self.baseURL = url
        if not url.endswith('/'):
            self.baseURL += '/'

        postData = { 'host': host }
        if token:
            postData['token'] = token
        self.loginData = postData

        response = self.session.post(self.baseURL + "login", data=postData)
        if response.status_code != requests.codes.ok:
            response.raise_for_status()

        if prevSet:
            f = self.getBackupSetInfo(prevSet)
            if f:
                self.prevBackupSet = f['backupset']
                self.prevBackupDate = f['starttime']
                self.lastClientTime = f['clienttime']
                self.prevBackupName = prevSet
            #self.cursor.execute = ("SELECT Name, BackupSet FROM Backups WHERE Name = :backup", {"backup": prevSet})
        else:
            b = self.lastBackupSet()
            self.prevBackupName = b['name']
            self.prevBackupSet  = b['backupset']
            self.prevBackupDate = b['starttime']
            self.lastClientTime = b['clienttime']
        self.logger.debug("Last Backup Set: {} {} ".format(self.prevBackupName, self.prevBackupSet))

    def _bset(self, current):
        """ Determine the backupset we're being asked about.
            True == current, false = previous, otherwise a number is returned
        """
        if type(current) is bool:
            return str(self.currBackupSet) if current else str(self.prevBackupSet)
        else:
            return str(current)

    def listBackupSets(self):
        r = self.session.get(self.baseURL + "listBackupSets")
        r.raise_for_status()
        return r.json()

    def lastBackupSet(self, completed=True):
        r = self.session.get(self.baseURL + "lastBackupSet/" + str(int(completed)))
        r.raise_for_status()
        return r.json()

    def getBackupSetInfo(self, name):
        r = self.session.get(self.baseURL + "getBackupSetInfo/" + name)
        r.raise_for_status()
        return r.json()

    def getBackupSetInfoForTime(self, time):
        r = self.session.get(self.baseURL + "getBackupSetForTime/" + str(time))
        r.raise_for_status()
        return r.json()

    def getFileInfoByName(self, name, parent, current=True):
        bset = self._bset(current)
        (inode, device) = parent
        r = self.session.get(self.baseURL + "getFileInfoByName/" + bset + "/" + str(device) + "/" + str(inode) + "/" + name)
        r.raise_for_status()
        return r.json()

    def getFileInfoByPath(self, path, current=False):
        bset = self._bset(current)
        if not path.startswith('/'):
            path = '/' + path
        r = self.session.get(self.baseURL + "getFileInfoByPath/" + bset + path)
        r.raise_for_status()
        return r.json()

    def readDirectory(self, dirNode, current=False):
        (inode, device) = dirNode
        bset = self._bset(current)
        r = self.session.get(self.baseURL + "readDirectory/" + bset + "/" + str(device) + "/" + str(inode))
        r.raise_for_status()
        return r.json()

    def getChecksumByPath(self, path, current=False):
        bset = self._bset(current)
        if not path.startswith('/'):
            path = '/' + path
        r = self.session.get(self.baseURL + "getChecksumByPath/" + bset + path)
        r.raise_for_status()
        return r.json()

    def getChecksumInfo(self, checksum):
        r = self.session.get(self.baseURL + "getChecksumInfo/" + checksum)
        r.raise_for_status()
        return r.json()

    def getFirstBackupSet(self, name, current=False):
        bset = self._bset(current)
        r = self.session.get(self.baseURL + "getFirstBackupSet/" + bset + "/" + name)
        r.raise_for_status()
        return r.json()

    def getChainLength(self, checksum):
        r = self.session.get(self.baseURL + "getChainLength/" + checksum)
        r.raise_for_status()
        return r.json()

    def open(self, checksum, mode):
        temp = tempfile.SpooledTemporaryFile("wb")
        r = self.session.get(self.baseURL + "getFileData/" + checksum)
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=64 * 1024):
            temp.write(chunk)

        temp.seek(0)
        return temp