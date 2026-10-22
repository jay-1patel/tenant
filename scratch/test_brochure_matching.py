import sys
import os
sys.path.insert(0, os.path.abspath("."))

from backend.services.brochure_service import get_relevant_brochure


print("Testing get_relevant_brochure for dlf:")
b1 = get_relevant_brochure(button_id="menu_brochure", tenant_id="dlf")
print("menu_brochure:", b1.name if b1 else None, b1.url if b1 else None)

b2 = get_relevant_brochure(query="Can you send the Dahlias brochure?", tenant_id="dlf")
print("Dahlias query:", b2.name if b2 else None, b2.url if b2 else None)

b3 = get_relevant_brochure(query="Privana south pdf floor plan", tenant_id="dlf")
print("Privana query:", b3.name if b3 else None, b3.url if b3 else None)
