from aiogram.fsm.state import State, StatesGroup

class MailStates(StatesGroup):
    waiting_for_name = State()
