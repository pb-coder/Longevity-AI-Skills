# File Generation

## Column Schema

**Strength / bodyweight:**

| Date | # | Exercise | Set | Reps | kg | Volume | Notes |

**If any cardio present, extend all rows:**

| Date | # | Exercise | Set | Reps | kg | Volume | Notes | Distance (km) | Duration (min) | Pace (min/km) | Avg HR |

Non-cardio rows leave extended columns blank.

## Rules

- Use openpyxl. No formatting, no bold, no colors, no column widths, no formulas. Raw values only.
- Multiple workouts in one `/log` message → single file, sorted by date ascending.
- Save to `/mnt/user-data/outputs/workout_log.xlsx`, then present the file.

## Template

```python
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Workout Log"

headers = ["Date", "#", "Exercise", "Set", "Reps", "kg", "Volume", "Notes"]
# If cardio present, extend:
# headers += ["Distance (km)", "Duration (min)", "Pace (min/km)", "Avg HR"]
ws.append(headers)

# Data rows — plain strings/numbers, no formatting
ws.append(["2026-04-07", 1, "Jumping Jacks", 1, 60, 0, 0, ""])
# ... etc

wb.save("/mnt/user-data/outputs/workout_log.xlsx")
```

## Example

Input:
```
/log 22.02
* Jumping Jacks: 50
* Dumbbell Flat Bench Press 56kg x 8 /// 52kg x 7
* skull crushers 20k x 12 /// 20k x 10 (elbow felt off)
* treadmill 5k 28min avg hr 155
```

Output in chat:

```
Logging workout from 2026-02-22
[file presented]
1 workout, 4 exercises, 6 total sets, 1252kg total volume
```
