import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from services.intent_answers import answer_for_menu_title
wa = "919512777899"
for t in ["🏆 Benefits", "🛠️ Customer Support", "🧠 Technologies"]:
    print("=" * 60)
    print(t)
    print(answer_for_menu_title(wa, t))
