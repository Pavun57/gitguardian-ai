def get_user(cursor, username):
    cursor.execute("SELECT * FROM users WHERE name = '%s'" % username)
    return cursor.fetchone()
