import streamlit as st
from generate_report import generate_inventory_report

st.set_page_config(page_title="Inventory Report Generator", layout="wide")
st.title("📦 Inventory Distribution Report")
st.markdown("Upload your `SCHOOL STOCK.xlsx` file and get a detailed report with per‑branch tabs, required stock, and inter‑branch transfers.")

uploaded_file = st.file_uploader("Choose an Excel file", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner("Generating report... This may take a moment."):
        try:
            excel_bytes = generate_inventory_report(uploaded_file)
            st.success("✅ Report generated successfully!")
            st.download_button(
                label="📥 Download Inventory Report (Excel)",
                data=excel_bytes,
                file_name="Inventory_Report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"Error: {e}")
            st.exception(e)
