import pymysql

pymysql.install_as_MySQLdb()
import MySQLdb

if MySQLdb.version_info < (2, 2, 1):
    MySQLdb.version_info = (2, 2, 1, "final", 0)