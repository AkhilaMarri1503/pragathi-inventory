import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
import io
from datetime import datetime

# Page config
st.set_page_config(page_title="Pragathi Shoes Inventory", layout="wide")

# Title
st.title("👞 Pragathi Shoes Inventory Management System")
st.markdown("---")

# Sidebar for file upload
with st.sidebar:
    st.header("📁 Upload Inventory File")
    uploaded_file = st.file_uploader("Choose SCHOOL STOCK.csv", type=["csv"])
    st.markdown("---")
    st.caption("Version 1.0 | Pragathi Shoes")

# Main content
if uploaded_file:
    with st.spinner("Processing inventory data..."):
        # Read the CSV
        df = pd.read_csv(uploaded_file, header=None)
        
        # Parse the data
        processed_data = []
        for _, row in df.iterrows():
            try:
                desc = str(row[16])
                if " - " in desc and len(desc) > 10:
                    parts = desc.split(" - ")
                    if len(parts) >= 5:
                        processed_data.append({
                            "Branch": str(row[15]).strip(),
                            "Product": parts[0].strip(),
                            "Colour": parts[1].strip(),
                            "Size": parts[2].strip(),
                            "Article": parts[3].strip(),
                            "MRP": parts[4].strip(),
                            "Stock": float(row[17]) if row[17] else 0
                        })
            except:
                continue
        
        data_df = pd.DataFrame(processed_data)
        
        # Calculate dispatch needs (Target 6 units, alert below 3)
        TARGET = 6
        ALERT_LEVEL = 3
        data_df['Needed'] = data_df.apply(lambda x: max(0, TARGET - x['Stock']) if x['Stock'] < ALERT_LEVEL else 0, axis=1)
        data_df['Status'] = data_df['Stock'].apply(lambda x: '🔴 Low Stock' if x < ALERT_LEVEL else '🟢 Adequate')
        
        # Create tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📋 Inventory List", "🚚 Dispatch Orders", "📈 Analytics"])
        
        # TAB 1: Dashboard
        with tab1:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total SKUs", len(data_df))
            with col2:
                st.metric("Total Stock (Units)", int(data_df['Stock'].sum()))
            with col3:
                st.metric("Items Low Stock", len(data_df[data_df['Stock'] < ALERT_LEVEL]))
            with col4:
                st.metric("Units to Dispatch", int(data_df['Needed'].sum()))
            
            st.markdown("---")
            
            # Branch wise summary
            st.subheader("🏪 Stock Summary by Branch")
            branch_summary = data_df.groupby('Branch').agg({
                'Stock': 'sum',
                'Product': 'count'
            }).rename(columns={'Product': 'SKU Count'}).reset_index()
            branch_summary['Stock'] = branch_summary['Stock'].astype(int)
            st.dataframe(branch_summary, use_container_width=True)
            
            # Low stock alert
            low_stock = data_df[data_df['Stock'] < ALERT_LEVEL]
            if not low_stock.empty:
                st.warning(f"⚠️ {len(low_stock)} items are running low!")
                st.dataframe(low_stock[['Branch', 'Product', 'Size', 'Stock']], use_container_width=True)
        
        # TAB 2: Inventory List
        with tab2:
            st.subheader("Complete Inventory List")
            
            # Search filter
            search = st.text_input("🔍 Search by Product or Branch", "")
            if search:
                filtered = data_df[data_df['Product'].str.contains(search, case=False) | data_df['Branch'].str.contains(search, case=False)]
                st.dataframe(filtered, use_container_width=True, height=400)
            else:
                st.dataframe(data_df, use_container_width=True, height=400)
            
            # Export button
            csv = data_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Full Report (CSV)", csv, f"inventory_report_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
        
        # TAB 3: Dispatch Orders
        with tab3:
            st.subheader("🚚 Generate Dispatch Orders")
            
            # Branch selector
            branch_list = ['All Branches'] + sorted(data_df['Branch'].unique().tolist())
            selected_branch = st.selectbox("Select Branch", branch_list)
            
            if selected_branch == 'All Branches':
                needs = data_df[data_df['Needed'] > 0]
            else:
                needs = data_df[(data_df['Branch'] == selected_branch) & (data_df['Needed'] > 0)]
            
            if not needs.empty:
                st.info(f"📦 {len(needs)} items need restocking - Total {int(needs['Needed'].sum())} units")
                st.dataframe(needs[['Branch', 'Product', 'Size', 'Colour', 'Stock', 'Needed']], use_container_width=True)
                
                if st.button("📄 Generate Official Dispatch Order", type="primary"):
                    # Create PDF
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 16)
                    pdf.cell(200, 10, "PRAGATHI SHOES", ln=True, align='C')
                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(200, 10, "OFFICIAL DISPATCH ORDER", ln=True, align='C')
                    pdf.set_font("Arial", size=10)
                    pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
                    pdf.ln(10)
                    
                    # Table header
                    pdf.set_font("Arial", 'B', 10)
                    pdf.cell(50, 10, "Branch", 1)
                    pdf.cell(50, 10, "Product", 1)
                    pdf.cell(30, 10, "Size", 1)
                    pdf.cell(30, 10, "Current", 1)
                    pdf.cell(30, 10, "To Send", 1)
                    pdf.ln()
                    
                    # Table data
                    pdf.set_font("Arial", size=9)
                    for _, row in needs.iterrows():
                        pdf.cell(50, 8, str(row['Branch'])[:48], 1)
                        pdf.cell(50, 8, str(row['Product'])[:48], 1)
                        pdf.cell(30, 8, str(row['Size'])[:28], 1)
                        pdf.cell(30, 8, str(int(row['Stock'])), 1)
                        pdf.cell(30, 8, str(int(row['Needed'])), 1)
                        pdf.ln()
                    
                    pdf.ln(5)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.cell(200, 5, "Authorized Signature: ____________________", ln=True)
                    pdf.cell(200, 5, "Warehouse Manager", ln=True)
                    
                    # Save PDF
                    pdf_output = pdf.output(dest='S').encode('latin-1')
                    st.download_button("✅ Download Dispatch Order (PDF)", data=pdf_output, file_name=f"dispatch_order_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
                    st.success("Dispatch order generated successfully!")
            else:
                st.success("✅ No dispatch needed! All branches have adequate stock.")
        
        # TAB 4: Analytics
        with tab4:
            st.subheader("Inventory Analytics")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Top 10 Most Stocked Items**")
                top_items = data_df.nlargest(10, 'Stock')[['Product', 'Size', 'Stock']]
                st.dataframe(top_items, use_container_width=True)
            
            with col2:
                st.markdown("**Items Needing Restock**")
                restock_items = data_df[data_df['Needed'] > 0].nlargest(10, 'Needed')[['Product', 'Branch', 'Size', 'Needed']]
                if not restock_items.empty:
                    st.dataframe(restock_items, use_container_width=True)
                else:
                    st.info("No items need restocking")
            
            st.markdown("---")
            st.markdown("**Stock Distribution by Product Type**")
            product_summary = data_df.groupby('Product')['Stock'].sum().reset_index().sort_values('Stock', ascending=False)
            st.dataframe(product_summary, use_container_width=True)

else:
    # Show instructions when no file uploaded
    st.info("👈 **Please upload your SCHOOL STOCK.csv file using the sidebar**")
    
    st.markdown("""
    ### 📋 How to Use This System:
    
    1. **Click "Browse files"** in the left sidebar
    2. **Select your SCHOOL STOCK.csv** file from your computer
    3. **View the dashboard** with automatic stock analysis
    4. **Generate dispatch orders** for low-stock items
    5. **Export reports** as CSV or PDF
    
    ### 📊 What You Can Do:
    - ✅ Automatic stock level monitoring
    - ✅ Low stock alerts (below 3 units)
    - ✅ Dispatch order generation with PDF
    - ✅ Branch-wise inventory summary
    - ✅ Export data to CSV for records
    
    ### 📁 File Format Required:
    The system expects the SCHOOL STOCK.csv file from Pragathi Shoes inventory system.
    """)
    
    st.markdown("---")
    st.caption("Ready to upload your file. Click 'Browse files' in the left sidebar to begin.")