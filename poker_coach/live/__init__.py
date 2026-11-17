"""Live table reader: for play-money tournaments and research.

Reads a poker table from the screen, works out the situation and shows what
the coach would do, in a small window.  It never clicks or acts for the
player, and by default it only gives advice at tables it can confirm are
played for play money.

    schema.py   what a reading of the table contains
    reader.py   screenshot -> reading (Claude's vision), or a saved reading (JSON)
    decide.py   reading -> the engine's decision, and the play-money check
    capture.py  screen grab of the table, and when to read (the action buttons appear)
    app.py      the loop, the window, setup and the session log

Commands: ``live-setup`` (mark the table on the screen once), ``live`` (run),
``live-test`` (read one saved screenshot or reading and print the decision).
"""
