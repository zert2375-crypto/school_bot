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
    waiting_for_homework_choice = State() # Выбор задания из инлайн-клавиатуры
    waiting_for_photo = State()           # Отправка самого фото

class AIChatState(StatesGroup):
    chatting = State()  # Состояние, когда пользователь общается с нейросетью по конкретной задаче