"""The table app: a manual table tracker and coach for study and play money.

The user types or clicks what they see at the table; nothing here reads the
screen and nothing clicks for them.

    defaults.py   what a user may want to edit: blind ladders, stacks, presets
    amounts.py    one parser for every typed amount (1300, 12.5k, 25bb, 3x, 66%)
    model.py      the session: seats, the hand as an event list, replay, pots, undo, saving
"""
