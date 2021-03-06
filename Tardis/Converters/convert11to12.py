import sqlite3
import sys
import os.path
import logging

import convertutils

version = 11

def upgrade(conn, logger):
    convertutils.checkVersion(conn, version, logger)
    ###
    # Do this all 'manually', because a SQL only version seems to throw SQLite3 into an infinite loop.
    # Would be much cleaner if UPDATE supported an AS keyword, like SELECT does.

    conn.execute("PRAGMA journal_mode=truncate")

    convertutils.updateVersion(conn, version, logger)
    conn.commit()

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger('')

    if len(sys.argv) > 1:
        db = sys.argv[1]
    else:
        db = "tardis.db"

    conn = sqlite3.connect(db)
    upgrade(conn, logger)
