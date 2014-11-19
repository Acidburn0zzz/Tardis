Tardis
======

A TimeMachine that mostly works.

Tardis is a system for making incremental backups of filesystems, much like Apple's TimeMachine,
although not quite as polished.

Tardis began due to some frustrations with using pure rsync to do backups.  Tardis is more efficient with disk space,
it's able to coalesce duplicate copies of files, and stores file metadata separately from file data.  Tardis is also aimed
at having a relatively compact server, capable of running on small machines, such as a Raspberry PI.  Tardis is (hopefully)
relatively platform independent, although it's only been tested on linux so far.  It should work on MacOS, and should be
easy ported to Windows.

Tardis consists of several components:
* tardisd (TardisDaemon): The tardis daemon process which maintains the backups
* tardis  (TardisClient): The tardis client process, which creates backup data and pushes it to the server
* TardisFS: A FUSE based file system which provides views of the various backup sets.
* regenerate (Regenerate): A program to retrieve an individual verson of the file without using the TardisFS

Tardis is currently under development, but appears to be sufficiently bug free to start some use.
Features currently planned to be implemented:

1. ~~Handling multiple filesystems~~ (mostly handled.  Some potential issues)
2. Saving of extended attributes
2. ~~Saving of per-connection configuration values in the server DB~~
3. ~~Authentication of password~~
4. Encrypted encryption key stored on server, decrypted on client?
5. ~~User authentication capability (this differs from 3 above. 3 is to make sure the password/encryption key remains the same.  Currently different backup sessions could use different keys, and basically create a mess of everything).~~
6. ~~Python EGG setup.~~
7. ~~Better daemon support.~~
8. ~~LSB init script (systemctl support)?~~
9. Space management.  Multiple purge schedules for different prioritys.  On demand purging when low on space.
10. ~~Client side configuration files.~~ (as argument files)
11. ~~Stand alone execution (no need for separate server)~~
12. Remote access to data and files.
13. ~~Read password without echo.~~

Tardis relies on the bson, xattrs, pycrypto, and daemonize packages.
~~Tardis currently uses the librsync from rdiff-backup, but I hope to remove that soon.~~
Tardis uses the librsync package, but since that is not current on pypi, it's copied in here.  When/if a correct functional version appears on Pypi, we'll use it instead.  See https://github.com/smartfile/python-librsync

Setup
=====
Setting up the server is relatively straightforward.
  * Install ~~rdiff_backup~~ and librsync
    * Fedora: yum install librsync ~~rdiff_backup~~
    * Ubuntu: apt-get install librsync ~~rdiff_backup~~
    * Note, for builds past the 0.6 release, rdiff_backup is no longer needed.
  * Run the python setup:
    * python setup.py install
  * Edit the config file, tardisd.cfg (in /etc, should you so desire)
  * Set the BaseDir variable to point at a location to store all your databases.
  * Set the port to be the port you want to use.  Default is currently 9999.
  * If you want to use SSL, create a certificate and a key file (plenty of directions on the web).
  * Edit other parameters as necessary.
  * Copy the appropriate startup script as desired
      * Systemd/systemctl
         * cp init/tardisd.service /usr/lib/systemd/system
         * systemctl enable tardisd.service
      * SysV init
         * cp init/tardisd /etc/init.d
         * chkconfig --add tardisd
         * chkconfig tardisd on
         * service tardisd start

Running the Client
==================
Should probably run as root.  Basic operation is thus:
  tardis [--port <targetPort>] --server <host> [--ssl] -A /path/to/directory-to-backup <more paths here>
Use the --ssl if your connection is SSL enabled.
If you wish encrypted backups, add the --password or --password-file options to specify a password.  Note, if you use encrypted backups, you must always specify the same password.  Tardis doesn't currently check, but you're in a heap of pain of you get it wrong.  Or at least a LOT of wasted disk space, and unreadable files.

Your first backup will take quite a while.  Subsequent backups will be significantly faster.

Once you have an initial backup in place, put this in your cron job to run daily.
You can also run hourly incremental backups with a -H option instead of the -A above.
Adding --purge to your command line will remove old backupsets per a schedule of hourly's after a day, daily's after 30 days, weekly's after 6 months, and monthly's never.

Mounting the filesystem
=======================
The backup sets can be mounted as a filesystem, thus:
   tardisfs -o database=/path/to/database [-o host=hostname] [-o password=[your_password]] mountpoint
/path/to/the/backup/directory will be the path specified in the BaseDir in the server host config.  The host parameter is the name of the host that you wish to mount backups for.

Password should only be set if a password is specified in the backup.  If you leave it blank (ie, password=), it will prompt you for a password during mount.

Other options are available via -help.  (details TBD)


