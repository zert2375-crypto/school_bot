from aiogram.fsm.state import State, StatesGroup

class AddHomework(StatesGroup):
    subject = State()
    task = State()
    task_group2 = State()
    due_date = State()
    photo = State()
    textbook = State()

class EditHomework(StatesGroup):
    select_hw = State()
    new_task = State()
    new_textbook = State()
    new_photo = State()

class AddTaskPhoto(StatesGroup):
    waiting_for_photo = State()
    waiting_for_subject = State()
    waiting_for_task_number = State()