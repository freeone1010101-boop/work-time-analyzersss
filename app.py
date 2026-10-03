
import io
import re
from datetime import datetime, time

import pandas as pd
import streamlit as st

COMPANY_START = "09:30"
COMPANY_END = "18:30"

st.set_page_config(page_title="Work Time Analyzer", page_icon="⏱️", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-left: 1rem; padding-right: 1rem;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
@media (max-width: 700px) {
  .block-container {padding-left: .65rem; padding-right: .65rem;}
  [data-testid="stMetricValue"] {font-size: 1.2rem;}
  h1 {font-size: 1.7rem !important;}
  h2 {font-size: 1.35rem !important;}
  h3 {font-size: 1.1rem !important;}
}
</style>
""", unsafe_allow_html=True)


# ---------------- Authentication ----------------
# Five-user cloud-friendly login. No local database is required.
# Change these temporary passwords before company use.
USERS = {
    "admin": ("Admin@123", "admin"),
    "user1": ("Work@123", "user"),
    "user2": ("Work@123", "user"),
    "user3": ("Work@123", "user"),
    "user4": ("Work@123", "user"),
}

def authenticate(username, password):
    item = USERS.get(username)
    if item and item[0] == password:
        return {"username": username, "role": item[1]}
    return None

def login():
    st.markdown("# ⏱️ Work Time Analyzer")
    st.caption("Company attendance analysis")
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Sign in", use_container_width=True)
    if ok:
        user = authenticate(u, p)
        if user:
            st.session_state.user = user
            st.rerun()
        st.error("Invalid username or password.")

if "user" not in st.session_state:
    login()
    st.stop()

user = st.session_state.user
with st.sidebar:
    st.success(f"Signed in: {user['username']}")
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()

# ---------------- Time helpers ----------------
def minutes(v):
    if pd.isna(v) or v is None or str(v).strip()=="":
        return None
    if isinstance(v,(datetime,time)):
        return v.hour*60+v.minute+v.second/60
    s=str(v).strip()
    for f in ("%H:%M:%S","%H:%M","%I:%M:%S %p","%I:%M %p"):
        try:
            d=datetime.strptime(s,f)
            return d.hour*60+d.minute+d.second/60
        except ValueError:
            pass
    return None

def duration_minutes(v):
    if pd.isna(v) or str(v).strip()=="":
        return 0
    m=re.match(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}))?",str(v).strip())
    if not m:
        return 0
    return int(m.group(1))*60+int(m.group(2))+int(m.group(3) or 0)/60

def fmt(v):
    if v is None or pd.isna(v): return "00:00"
    v=max(0,int(round(v)))
    return f"{v//60:02d}:{v%60:02d}"

def employee_name(v):
    s=str(v).strip()
    m=re.match(r"^\s*\d+\s*:\s*(.*)$",s)
    return m.group(1).strip() if m else s

def day_columns(raw, header_row=6):
    cols=[]
    for c,v in enumerate(raw.iloc[header_row].tolist()):
        if isinstance(v,str) and re.match(r"^\s*\d+\s+",v):
            cols.append(c)
    return cols

# ---------------- Exact parser for the supplied report ----------------
def parse_attendance(raw):
    emp_rows=[]
    for r in range(len(raw)):
        for c in range(min(8,raw.shape[1])):
            v=raw.iat[r,c]
            if isinstance(v,str) and v.strip().lower()=="employee:":
                emp_rows.append(r); break
    if not emp_rows:
        raise ValueError("This file does not look like the supported Monthly Status Report format.")

    # Find the day header dynamically.
    header_row=next((r for r in range(min(15,len(raw)))
                     if any(isinstance(v,str) and v.strip().lower()=="days" for v in raw.iloc[r].tolist())),6)
    cols=day_columns(raw,header_row)

    summaries=[]
    audit=[]
    for i,er in enumerate(emp_rows):
        stop=emp_rows[i+1] if i+1<len(emp_rows) else len(raw)
        # Employee label/name: look across the employee row.
        name=""
        for v in raw.iloc[er].tolist():
            if isinstance(v,str) and re.search(r"^\s*\d+\s*:",v):
                name=employee_name(v); break
        if not name: name=f"Employee {i+1}"

        rowmap={}
        for r in range(er+1,min(er+12,stop)):
            label=str(raw.iat[r,0]).strip().lower() if pd.notna(raw.iat[r,0]) else ""
            if label in {"status","intime","outtime","duration","late by","early by","ot","shift"}:
                rowmap[label]=r

        if "status" not in rowmap:
            continue

        # The supplied report already contains the company's detailed Duration and OT.
        # These are treated as the authoritative source because they preserve the exact
        # attendance-system calculation (including any hidden seconds).
        total_work=total_ot=0
        present=absent=weekly=holiday=leave=0
        late=early=0
        late_days=early_days=0

        for c in cols:
            status=str(raw.iat[rowmap["status"],c]).strip().upper() if pd.notna(raw.iat[rowmap["status"],c]) else ""
            if not status: continue

            if status=="P": present += 1
            elif status=="A": absent += 1
            elif status=="WO": weekly += 1
            elif status=="WOP": present += 1; weekly += 1
            elif status in {"H","HOL","HOLIDAY"}: holiday += 1
            elif status in {"L","LEAVE"}: leave += 1

            d = duration_minutes(raw.iat[rowmap["duration"],c]) if "duration" in rowmap else 0
            o = duration_minutes(raw.iat[rowmap["ot"],c]) if "ot" in rowmap else 0
            total_work += d
            total_ot += o

            late_v = duration_minutes(raw.iat[rowmap["late by"],c]) if "late by" in rowmap else 0
            early_v = duration_minutes(raw.iat[rowmap["early by"],c]) if "early by" in rowmap else 0
            late += late_v; early += early_v
            late_days += late_v > 0
            early_days += early_v > 0

            inv=raw.iat[rowmap["intime"],c] if "intime" in rowmap else ""
            outv=raw.iat[rowmap["outtime"],c] if "outtime" in rowmap else ""
            day=str(raw.iat[header_row,c]).strip() if pd.notna(raw.iat[header_row,c]) else str(c)

            # Independent rule check shown to the user, not used to overwrite the
            # source-system duration. Early arrival is excluded and post-18:30 is OT.
            im=minutes(inv); om=minutes(outv)
            rule_work = max(0, om-max(im,570)) if im is not None and om is not None and om>im else 0
            rule_ot = max(0, om-1110) if om is not None else 0

            audit.append({
                "Employee":name, "Day":day, "Status":status,
                "IN":str(inv) if pd.notna(inv) else "",
                "OUT":str(outv) if pd.notna(outv) else "",
                "Report Work":fmt(d), "Report OT":fmt(o),
                "Rule Work (09:30 start)":fmt(rule_work),
                "Rule OT (after 18:30)":fmt(rule_ot),
                "Late":fmt(late_v), "Early":fmt(early_v)
            })

        summaries.append({
            "Employee":name,
            "Total Work Duration":fmt(total_work),
            "Total OT":fmt(total_ot),
            "Present":present,
            "Absent":absent,
            "WeeklyOff":weekly,
            "Holidays":holiday,
            "Leaves Taken":leave,
            "Late By Hrs":fmt(late),
            "Late By Days":int(late_days),
            "Early By Hrs":fmt(early),
            "Early going By Days":int(early_days),
            "Total Duration(+OT)":fmt(total_work+total_ot),
            "Average Working Hrs":fmt(total_work/present if present else 0)
        })

    return pd.DataFrame(summaries), pd.DataFrame(audit)

# ---------------- Interface ----------------
st.title("Work Time Analysis Dashboard")
st.caption("Upload → Analyze → Verify → Export")

uploaded=st.file_uploader("Upload Monthly Status Report (.xls or .xlsx)", type=["xls","xlsx"])

if uploaded is None:
    st.info("Upload the attendance report to begin.")
    st.markdown("""
### Company calculation policy
- Company start: **09:30 AM**
- Company end: **06:30 PM**
- Arrival before 09:30 is not added to normal work time.
- Work after 18:30 is overtime.
- The supplied attendance report's **Duration** and **OT** rows are preserved as the authoritative totals when available.
""")
    st.stop()

try:
    engine="xlrd" if uploaded.name.lower().endswith(".xls") else None
    raw=pd.read_excel(uploaded,header=None,engine=engine)
    summary,audit=parse_attendance(raw)
except Exception as e:
    st.error(f"Could not analyze the file: {e}")
    st.stop()

if summary.empty:
    st.warning("No employees found.")
    st.stop()

def sumdur(series):
    return sum(duration_minutes(x) for x in series)

a,b,c,d=st.columns(4)
a.metric("Employees",len(summary))
b.metric("Present Days",int(summary["Present"].sum()))
c.metric("Total Work",fmt(sumdur(summary["Total Work Duration"])))
d.metric("Total OT",fmt(sumdur(summary["Total OT"])))

t1,t2,t3,t4=st.tabs(["Employee Summary","Employee Detail","Daily Audit","Export"])

with t1:
    st.dataframe(summary,use_container_width=True,hide_index=True)

with t2:
    emp=st.selectbox("Select employee",summary["Employee"].tolist())
    r=summary[summary.Employee==emp].iloc[0]
    st.subheader(emp)
    fields=list(summary.columns[1:])
    cards=st.columns(4)
    for i,f in enumerate(fields):
        cards[i%4].metric(f,str(r[f]))

with t3:
    emp2=st.selectbox("Audit employee",summary["Employee"].tolist(),key="audit")
    st.dataframe(audit[audit.Employee==emp2],use_container_width=True,hide_index=True)
    st.caption("Rule Work/Rule OT is an independent check. Report Work/Report OT preserves the exact detailed values from the uploaded attendance system.")

with t4:
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer:
        summary.to_excel(writer,sheet_name="Employee Summary",index=False)
        audit.to_excel(writer,sheet_name="Daily Audit",index=False)
    out.seek(0)
    st.download_button("Download Complete Report",out.getvalue(),
                       "Work_Time_Analysis.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


st.caption("Work Time Analyzer • Mobile-friendly web application")
