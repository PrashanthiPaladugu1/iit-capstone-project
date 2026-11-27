import sys; sys.path.insert(0, ".")
from streamlit.testing.v1 import AppTest
def app():
    import ui_app; ui_app.render()
at = AppTest.from_function(app, default_timeout=240)
at.run()
at.chat_input[0].set_value("What is the RSI of ITC?").run()
print("exception:", at.exception)
print([m.value[:300] for m in at.markdown if "RSI" in m.value])
