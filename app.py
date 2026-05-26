import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import io

st.set_page_config(page_title="Inventory Management System", layout="wide")

st.title("📦 Universal Inventory Management System")

# ============================================
# FILE FORMAT DETECTION & PARSING
# ============================================

def detect_file_format(df):
    """Auto-detect what type of file was uploaded"""
    
    # Check for SCHOOL STOCK format (has many columns, data in col 15,16,17)
    if df.shape[1] > 17:
        return "school_stock"
    
    # Check for standard format with headers
    elif any(col.lower() in ['product', 'sku', 'item'] for col in df.columns.str.lower()):
        return "standard_headers"
    
    # Check for simple format (Product, Quantity)
    elif df.shape[1] == 2:
        return "simple"
    
    # Check for export format (Product, Stock, Price)
    elif df.shape[1] >= 3:
        return "export"
    
    else:
        return "unknown"

def parse_school_stock(df):
    """Parse the specific SCHOOL STOCK.csv format"""
    data = []
    for _, row in df.iterrows():
        try:
            desc = str(row[16])
            if " - " in desc and len(desc) > 10:
                parts = desc.split(" - ")
                if len(parts) >= 5:
                    data.append({
                        "Branch": str(row[15]).strip(),
                        "Product": parts[0].strip(),
                        "Colour": parts[1].strip(),
                        "Size": parts[2].strip(),
                        "Article": parts[3].strip(),
                        "MRP": parts[4].strip(),
                        "Quantity": float(row[17]) if row[17] else 0
                    })
        except:
            continue
    return pd.DataFrame(data)

def parse_standard_headers(df):
    """Parse CSV with standard column headers"""
    # Map common column names
    col_mapping = {}
    
    for col in df.columns:
        col_lower = col.lower()
        if 'product' in col_lower or 'item' in col_lower or 'sku' in col_lower:
            col_mapping['product'] = col
        elif 'qty' in col_lower or 'quantity' in col_lower or 'stock' in col_lower:
            col_mapping['quantity'] = col
        elif 'price' in col_lower or 'mrp' in col_lower:
            col_mapping['price'] = col
        elif 'branch' in col_lower or 'store' in col_lower or 'location' in col_lower:
            col_mapping['branch'] = col
        elif 'size' in col_lower:
            col_mapping['size'] = col
        elif 'color' in col_lower or 'colour' in col_lower:
            col_mapping['colour'] = col
    
    # If we found at least product and quantity, use it
    if 'product' in col_mapping and 'quantity' in col_mapping:
        data = []
        for _, row in df.iterrows():
            record = {
                "Product": row[col_mapping['product']],
                "Quantity": float(row[col_mapping['quantity']]) if pd.notna(row[col_mapping['quantity']]) else 0
            }
            if 'branch' in col_mapping:
                record["Branch"] = row[col_mapping['branch']]
            else:
                record["Branch"] = "Main Store"
            if 'price' in col_mapping:
                record["Price"] = row[col_mapping['price']]
            if 'size' in col_mapping:
                record["Size"] = row[col_mapping['size']]
            if 'colour' in col_mapping:
                record["Colour"] = row[col_mapping['colour']]
            data.append(record)
        return pd.DataFrame(data)
    
    return None

def parse_simple_format(df):
    """Parse simple 2-column format (Product, Quantity)"""
    data = []
    for _, row in df.iterrows():
        data.append({
            "Product": str(row[0]),
            "Quantity": float(row[1]) if row[1] else 0,
            "Branch": "Main Store"
        })
    return pd.DataFrame(data)

def parse_export_format(df):
    """Parse typical export format"""
    # Assume first column is product, second is quantity
    data = []
    for _, row in df.iterrows():
        data.append({
            "Product": str(row[0]),
            "Quantity": float(row[1]) if len(row) > 1 and row[1] else 0,
            "Branch": str(row[2]) if len(row) > 2 else "Main Store"
        })
    return pd.DataFrame(data)

# ============================================
# MAIN APP
# ============================================

uploaded_file = st.sidebar.file_uploader(
    "Upload CSV File", 
    type=["csv"],
    help="Works with SCHOOL STOCK.csv, standard inventory exports, or any CSV with product data"
)

# File format selector (manual override)
format_option = st.sidebar.selectbox(
    "Or manually select format:",
    ["Auto-detect", "School Stock Format", "Standard Headers", "Simple (Product, Qty)", "Export Format (Product, Qty, Branch)"]
)

if uploaded_file:
    with st.spinner("Processing file..."):
        # Read the CSV
        df = pd.read_csv(uploaded_file, header=None)
        
        # Detect or use selected format
        if format_option == "Auto-detect":
            file_type = detect_file_format(df)
            st.sidebar.info(f"📁 Detected format: {file_type.replace('_', ' ').title()}")
        else:
            file_type = format_option.lower().replace(" ", "_")
        
        # Parse based on format
        data_df = None
        
        if file_type == "school_stock" or format_option == "School Stock Format":
            data_df = parse_school_stock(df)
            st.success("✅ Loaded SCHOOL STOCK format")
        
        elif file_type == "standard_headers" or format_option == "Standard Headers":
            # Try reading with headers
            df_header = pd.read_csv(uploaded_file)
            data_df = parse_standard_headers(df_header)
            if data_df is not None:
                st.success("✅ Loaded standard CSV with headers")
            else:
                st.error("Could not parse standard format. Try another option.")
        
        elif file_type == "simple" or format_option == "Simple (Product, Qty)":
            data_df = parse_simple_format(df)
            st.success("✅ Loaded simple format")
        
        elif file_type == "export" or format_option == "Export Format (Product, Qty, Branch)":
            data_df = parse_export_format(df)
            st.success("✅ Loaded export format")
        
        else:
            st.error("Could not detect file format. Please manually select from dropdown.")
        
        if data_df is not None and not data_df.empty:
            # Calculate low stock alerts
            TARGET = st.sidebar.number_input("Target Stock Level", value=6, min_value=1)
            ALERT = st.sidebar.number_input("Low Stock Alert Level", value=3, min_value=0)
            
            data_df['Needed'] = data_df.apply(
                lambda x: max(0, TARGET - x['Quantity']) if x['Quantity'] < ALERT else 0, 
                axis=1
            )
            data_df['Status'] = data_df['Quantity'].apply(
                lambda x: '🔴 Low Stock' if x < ALERT else ('🟡 Reorder Soon' if x < TARGET else '🟢 Adequate')
            )
            
            # TABS
            tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "📋 Inventory", "🚚 Reorder Report", "📈 Analytics"])
            
            with tab1:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total SKUs", len(data_df))
                with col2:
                    st.metric("Total Stock", int(data_df['Quantity'].sum()))
                with col3:
                    st.metric("Low Stock Items", len(data_df[data_df['Quantity'] < ALERT]))
                with col4:
                    st.metric("Units to Reorder", int(data_df['Needed'].sum()))
                
                st.markdown("---")
                
                # Branch summary (if branch column exists)
                if 'Branch' in data_df.columns:
                    st.subheader("🏪 Stock by Branch")
                    branch_summary = data_df.groupby('Branch')['Quantity'].sum().reset_index()
                    st.dataframe(branch_summary, use_container_width=True)
                
                # Low stock alert
                low_stock = data_df[data_df['Quantity'] < ALERT]
                if not low_stock.empty:
                    st.warning(f"⚠️ {len(low_stock)} items need attention!")
                    st.dataframe(low_stock[['Product', 'Quantity', 'Status']], use_container_width=True)
            
            with tab2:
                st.subheader("Complete Inventory")
                
                # Search
                search = st.text_input("🔍 Search", "")
                if search:
                    filtered = data_df[data_df['Product'].str.contains(search, case=False)]
                    st.dataframe(filtered, use_container_width=True)
                else:
                    st.dataframe(data_df, use_container_width=True)
                
                # Export
                csv = data_df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Export CSV", csv, f"inventory_{datetime.now().strftime('%Y%m%d')}.csv")
            
            with tab3:
                st.subheader("Reorder Recommendations")
                
                needs = data_df[data_df['Needed'] > 0]
                if not needs.empty:
                    st.info(f"📦 Need to reorder {len(needs)} items - Total {int(needs['Needed'].sum())} units")
                    st.dataframe(needs[['Product', 'Quantity', 'Needed']], use_container_width=True)
                    
                    if st.button("Generate Purchase Order"):
                        pdf = FPDF()
                        pdf.add_page()
                        pdf.set_font("Arial", 'B', 16)
                        pdf.cell(200, 10, "PURCHASE ORDER", ln=True, align='C')
                        pdf.set_font("Arial", size=10)
                        pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d')}", ln=True, align='C')
                        pdf.ln(10)
                        
                        pdf.set_font("Arial", 'B', 12)
                        pdf.cell(100, 10, "Product", 1)
                        pdf.cell(50, 10, "Current Stock", 1)
                        pdf.cell(40, 10, "To Order", 1)
                        pdf.ln()
                        
                        pdf.set_font("Arial", size=10)
                        for _, row in needs.iterrows():
                            pdf.cell(100, 8, str(row['Product'])[:48], 1)
                            pdf.cell(50, 8, str(int(row['Quantity'])), 1)
                            pdf.cell(40, 8, str(int(row['Needed'])), 1)
                            pdf.ln()
                        
                        pdf_output = pdf.output(dest='S').encode('latin-1')
                        st.download_button("📄 Download PDF", pdf_output, "purchase_order.pdf")
                else:
                    st.success("✅ No reorder needed!")
            
            with tab4:
                st.subheader("Analytics")
                
                # Top products
                st.markdown("**Top 10 Products by Stock**")
                top = data_df.nlargest(10, 'Quantity')[['Product', 'Quantity']]
                st.dataframe(top, use_container_width=True)
                
                # Stock distribution
                st.markdown("**Stock Status Distribution**")
                status_counts = data_df['Status'].value_counts()
                st.dataframe(status_counts, use_container_width=True)

else:
    # Instructions
    st.info("👈 Upload your CSV file to begin")
    
    st.markdown("""
    ### 📋 Supported File Formats:
    
    | Format | Description | Example |
    |--------|-------------|---------|
    | **School Stock** | Pragathi Shoes export | Your SCHOOL STOCK.csv |
    | **Standard Headers** | CSV with column names | Product, Quantity, Price |
    | **Simple Format** | 2 columns | Product, Stock |
    | **Export Format** | 3+ columns | Product, Qty, Branch |
    
    ### 🎯 What This App Does:
    - ✅ Auto-detects your file format
    - ✅ Calculates reorder needs
    - ✅ Generates purchase orders (PDF)
    - ✅ Exports reports (CSV)
    - ✅ Low stock alerts
    
    ### 📝 Tips:
    - Works with ANY CSV file
    - Manually select format if auto-detect fails
    - Adjust target stock levels in sidebar
    """)

st.sidebar.markdown("---")
st.sidebar.caption("Universal Inventory Manager v2.0")
