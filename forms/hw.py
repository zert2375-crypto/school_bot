from aiogram.fsm.state import State, StatesGroup

class AddHomework(StatesGroup):
    subject = State()
    task = State()
    task_group2 = State()
    due_date = State()
    photo = State()
