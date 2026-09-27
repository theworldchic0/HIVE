import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bottom_blueprint as bb
def test_current_window_day():
 x=bb.clock(date(2026,9,24)); assert x['state']=='BOTTOM_WINDOW_ACTIVE'; assert x['bottom_window_day']==6
def test_window_length(): assert bb.clock(date(2026,9,24))['bottom_window_total_days']==59
