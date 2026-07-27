#!/usr/bin/env python3
"""Generate an Excel file with LinkedIn Software Engineer jobs in Bengaluru."""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "Software Engineer Jobs - Bengaluru"

# ── Header styling ──
header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=12)
header_fill = PatternFill(start_color="0B66C2", end_color="0B66C2", fill_type="solid")
header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
thin_border = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

headers = [
    "S.No",
    "Job Title",
    "Company",
    "Location",
    "Posted",
    "LinkedIn URL",
]

for col_idx, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col_idx, value=header)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = header_alignment
    cell.border = thin_border

# ── Job data extracted from LinkedIn ──
jobs = [
    ("Software Engineer", "Microsoft", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-engineer-at-microsoft-4366861071"),
    ("Software Engineer", "Microsoft", "Bengaluru, Karnataka, India", "1 day ago", "https://in.linkedin.com/jobs/view/software-engineer-at-microsoft-4441243125"),
    ("Software Engineer", "Microsoft", "Bengaluru, Karnataka, India", "2 days ago", "https://in.linkedin.com/jobs/view/software-engineer-at-microsoft-4431755425"),
    ("Software Engineer", "Microsoft", "Bengaluru, Karnataka, India", "1 day ago", "https://in.linkedin.com/jobs/view/software-engineer-at-microsoft-4441223988"),
    ("Software Dev Engineer I", "Swiggy", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-dev-engineer-i-at-swiggy-4437547488"),
    ("Software Engineer III, Full Stack, Google Cloud", "Google", "Bengaluru, Karnataka, India", "2 weeks ago", "https://in.linkedin.com/jobs/view/software-engineer-iii-full-stack-google-cloud-at-google-4320959215"),
    ("Software Engineer", "Cisco", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-engineer-at-cisco-4436702583"),
    ("Software Engineer in Test", "Nykaa", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-engineer-in-test-at-nykaa-4436089917"),
    ("Software Engineer", "Cisco", "Bengaluru, Karnataka, India", "2 weeks ago", "https://in.linkedin.com/jobs/view/software-engineer-at-cisco-4434295443"),
    ("Software Engineer", "Cisco", "Bengaluru, Karnataka, India", "2 weeks ago", "https://in.linkedin.com/jobs/view/software-engineer-at-cisco-4434405187"),
    ("Software Development Engineer -IV (Backend)", "Groww", "Bengaluru, Karnataka, India", "22 hours ago", "https://in.linkedin.com/jobs/view/software-development-engineer-iv-backend-at-groww-4440708352"),
    ("Software Engineer", "Cisco", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-engineer-at-cisco-4438201127"),
    ("Software Engineer, Intern", "Stripe", "Bengaluru, Karnataka, India", "1 week ago", "https://in.linkedin.com/jobs/view/software-engineer-intern-at-stripe-4439021399"),
    ("Software Engineer III, Google Cloud", "Google", "Bengaluru, Karnataka, India", "4 days ago", "https://in.linkedin.com/jobs/view/software-engineer-iii-google-cloud-at-google-4402362994"),
    ("Associate Software Engineer", "MillerKnoll", "Bengaluru, Karnataka, India", "2 weeks ago", "https://in.linkedin.com/jobs/view/associate-software-engineer-at-millerknoll-4385603468"),
]

# ── Data cell styling ──
data_font = Font(name="Calibri", size=11)
link_font = Font(name="Calibri", size=11, color="0563C1", underline="single")
alt_fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")

for row_idx, (title, company, location, posted, url) in enumerate(jobs, 2):
    values = [row_idx - 1, title, company, location, posted, url]
    for col_idx, value in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=col_idx, value=value)
        cell.border = thin_border
        if col_idx == 6:
            cell.font = link_font
            cell.hyperlink = url
        else:
            cell.font = data_font
        cell.alignment = Alignment(vertical="center", wrap_text=(col_idx == 2))

    # Alternate row shading
    if (row_idx - 2) % 2 == 1:
        for col_idx in range(1, 7):
            ws.cell(row=row_idx, column=col_idx).fill = alt_fill

# ── Column widths ──
col_widths = [8, 45, 18, 32, 16, 70]
for i, w in enumerate(col_widths, 1):
    ws.column_dimensions[get_column_letter(i)].width = w

# ── Freeze top row ──
ws.freeze_panes = "A2"

# ── Auto-filter ──
ws.auto_filter.ref = f"A1:F{len(jobs) + 1}"

# ── Save ──
output_path = "/home/hasheem/Hasheem files/Hasheem sub foders/ai/LinkedIn_Jobs_Bengaluru.xlsx"
wb.save(output_path)
print(f"✅ Excel file saved to: {output_path}")
print(f"   Total jobs listed: {len(jobs)}")