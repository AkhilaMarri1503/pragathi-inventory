import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re

st.set_page_config(page_title="Pragathi Shoes - Sales-Driven Transfer System", layout="wide")

st.title("👞 Pragathi Shoes - Sales-Driven Stock Transfer System")
st.markdown("**Intelligent stock redistribution based on actual sales data**")

# ============================================
# BRANCH CONFIGURATION
# ============================================

BRANCHES = {
    "POPULAR SHOE COMPANY": {"target": 12, "min": 6, "name": "Popular Store", "order": 1},
    "PRAGATHI SHOES AMD 2": {"target": 8, "min": 4, "name": "AMD 2 Store", "order": 2},
    "PRAGATHI SHOES RAGOLU": {"target": 8, "min": 4, "name": "Ragolu Store", "order": 3},
    "PRAGATHI SHOES BALAGA": {"target": 8, "min": 4, "name": "Balaga Store", "order": 4},
    "PRAGATHI SHOES AKP": {"target": 8, "min": 4, "name": "AKP Store", "order": 5},
    "PRAGATHI SHOES": {"target": 20, "min": 10, "name": "Central Warehouse", "order": 6}
}

BRANCH_ORDER = ["POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU", 
                "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP", "PRAGATHI SHOES"]

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('→', '->')
    return text.strip()

# ============================================
# SALES DATA PROCESSING
# ============================================

def process_sales_file(uploaded_file):
    """Parse sales CSV and calculate demand"""
    
    df = pd.read_csv(uploaded_file)
    
    sales_data = {}
    
    # Try to detect sales file structure
    # Look for common column names
    possible_product_cols = ['product', 'item', 'sku', 'product_name', 'description']
    possible_qty_cols = ['quantity', 'qty', 'sold', 'sales_qty']
    possible_branch_cols = ['branch', 'store', 'location', 'branch_name']
    possible_date_cols = ['date', 'sale_date', 'transaction_date']
    
    product_col = None
    qty_col = None
    branch_col = None
    date_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if any(p in col_lower for p in possible_product_cols):
            product_col = col
        if any(q in col_lower for q in possible_qty_cols):
            qty_col = col
        if any(b in col_lower for b in possible_branch_cols):
            branch_col = col
        if any(d in col_lower for d in possible_date_cols):
            date_col = col
    
    if product_col is None or qty_col is None:
        st.error("Could not identify product and quantity columns in sales file")
        return None, None
    
    # Aggregate sales by branch and product
    if branch_col:
        sales_summary = df.groupby([branch_col, product_col])[qty_col].sum().reset_index()
        sales_summary.columns = ['Branch', 'Product', 'Sales_Qty']
    else:
        sales_summary = df.groupby(product_col)[qty_col].sum().reset_index()
        sales_summary.columns = ['Product', 'Sales_Qty']
        sales_summary['Branch'] = 'ALL'
    
    # Calculate sales velocity (if date column exists)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col])
        max_date = df[date_col].max()
        min_date = df[date_col].min()
        days = (max_date - min_date).days + 1
        sales_summary['Daily_Sales_Rate'] = sales_summary['Sales_Qty'] / days
        sales_summary['Weekly_Sales_Rate'] = sales_summary['Daily_Sales_Rate'] * 7
        sales_summary['Monthly_Sales_Rate'] = sales_summary['Daily_Sales_Rate'] * 30
    else:
        sales_summary['Daily_Sales_Rate'] = sales_summary['Sales_Qty'] / 30  # Assume 30 days
        sales_summary['Weekly_Sales_Rate'] = sales_summary['Daily_Sales_Rate'] * 7
        sales_summary['Monthly_Sales_Rate'] = sales_summary['Sales_Qty']
    
    return sales_summary, {"product_col": product_col, "qty_col": qty_col, "branch_col": branch_col}

# ============================================
# STOCK DATA PROCESSING
# ============================================

def process_stock_file(uploaded_file):
    """Parse stock CSV and organize by branch"""
    
    df = pd.read_csv(uploaded_file, header=None)
    
    all_items = []
    
    for _, row in df.iterrows():
        try:
            branch = str(row[15]).strip()
            desc = str(row[16]).strip()
            qty = float(row[17]) if row[17] else 0
            
            if " - " in desc and len(desc) > 10:
                parts = desc.split(" - ")
                if len(parts) >= 5:
                    all_items.append({
                        "Branch": branch,
                        "Product": parts[0].strip(),
                        "Colour": parts[1].strip(),
                        "Size": parts[2].strip(),
                        "Article": parts[3].strip(),
                        "MRP": parts[4].strip(),
                        "Quantity": qty
                    })
        except:
            continue
    
    df_items = pd.DataFrame(all_items)
    
    if df_items.empty:
        return None, None
    
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    
    # Create complete inventory matrix
    complete_inventory = {}
    
    for branch in BRANCHES.keys():
        branch_data = df_items[df_items['Branch'] == branch] if branch in df_items['Branch'].values else pd.DataFrame()
        
        sku_dict = {}
        if not branch_data.empty:
            for _, row in branch_data.iterrows():
                sku_dict[row['SKU']] = row['Quantity']
        
        branch_records = []
        for sku in all_skus:
            sku_row = df_items[df_items['SKU'] == sku].iloc[0] if not df_items[df_items['SKU'] == sku].empty else None
            
            if sku_row is not None:
                quantity = sku_dict.get(sku, 0)
                branch_records.append({
                    "Branch": branch,
                    "SKU": sku,
                    "Product": sku_row['Product'],
                    "Colour": sku_row['Colour'],
                    "Size": sku_row['Size'],
                    "Article": sku_row['Article'],
                    "MRP": sku_row['MRP'],
                    "Quantity": quantity
                })
        
        complete_inventory[branch] = pd.DataFrame(branch_records)
    
    return complete_inventory, all_skus

# ============================================
# DEMAND-DRIVEN TRANSFER CALCULATION
# ============================================

def calculate_sales_driven_transfers(complete_inventory, sales_data, branches_config):
    """Calculate transfers based on sales velocity and current stock"""
    
    all_transfers = []
    
    # Get all SKUs
    first_branch = next(iter(complete_inventory.values()))
    if first_branch.empty:
        return pd.DataFrame()
    
    all_skus = first_branch['SKU'].unique()
    
    for sku in all_skus:
        # Get SKU details
        sku_row = first_branch[first_branch['SKU'] == sku].iloc[0] if not first_branch.empty else None
        if sku_row is None:
            continue
        
        product_name = sku_row['Product']
        
        # Get sales data for this product
        product_sales = sales_data[sales_data['Product'].str.contains(product_name, case=False, na=False)] if not sales_data.empty else pd.DataFrame()
        
        for branch, config in branches_config.items():
            if branch == "PRAGATHI SHOES":
                continue
            
            # Get current stock
            current_stock = complete_inventory[branch][complete_inventory[branch]['SKU'] == sku]['Quantity'].iloc[0] if not complete_inventory[branch].empty else 0
            
            # Calculate demand-based target
            branch_sales = product_sales[product_sales['Branch'].str.contains(branch, case=False, na=False)] if not product_sales.empty and 'Branch' in product_sales.columns else product_sales
            
            if not branch_sales.empty:
                # Dynamic target based on sales velocity
                weekly_sales = branch_sales['Weekly_Sales_Rate'].iloc[0] if 'Weekly_Sales_Rate' in branch_sales.columns else branch_sales['Sales_Qty'].iloc[0] / 4
                # Target = 2 weeks of sales + safety stock
                dynamic_target = max(int(weekly_sales * 2) + config['min'], config['min'])
                dynamic_target = min(dynamic_target, 30)  # Cap at 30
            else:
                # No sales history, use default target
                dynamic_target = config['target']
            
            # Update target in config for this calculation
            config['effective_target'] = dynamic_target
            
            # Calculate surplus/deficit
            if current_stock > dynamic_target:
                surplus = current_stock - dynamic_target
                all_transfers.append({
                    "SKU": sku,
                    "Product": sku_row['Product'],
                    "Colour": sku_row['Colour'],
                    "Size": sku_row['Size'],
                    "Article": sku_row['Article'],
                    "MRP": sku_row['MRP'],
                    "Branch": branch,
                    "Current Stock": current_stock,
                    "Sales Driven Target": dynamic_target,
                    "Surplus": surplus,
                    "Status": "SURPLUS"
                })
            elif current_stock < config['min']:
                deficit = config['min'] - current_stock
                all_transfers.append({
                    "SKU": sku,
                    "Product": sku_row['Product'],
                    "Colour": sku_row['Colour'],
                    "Size": sku_row['Size'],
                    "Article": sku_row['Article'],
                    "MRP": sku_row['MRP'],
                    "Branch": branch,
                    "Current Stock": current_stock,
                    "Sales Driven Target": dynamic_target,
                    "Deficit": deficit,
                    "Status": "DEFICIT"
                })
    
    # Create transfer pairs
    transfer_pairs = []
    surplus_items = [t for t in all_transfers if t['Status'] == 'SURPLUS']
    deficit_items = [t for t in all_transfers if t['Status'] == 'DEFICIT']
    
    for surplus in surplus_items:
        for deficit in deficit_items[:]:
            if surplus['SKU'] == deficit['SKU'] and surplus['Surplus'] > 0 and deficit['Deficit'] > 0:
                transfer_qty = min(surplus['Surplus'], deficit['Deficit'])
                transfer_pairs.append({
                    "Product": surplus['Product'],
                    "Colour": surplus['Colour'],
                    "Size": surplus['Size'],
                    "Article": surplus['Article'],
                    "MRP": surplus['MRP'],
                    "From Branch": surplus['Branch'],
                    "From Stock": surplus['Current Stock'],
                    "From Target": surplus['Sales Driven Target'],
                    "To Branch": deficit['Branch'],
                    "To Stock": deficit['Current Stock'],
                    "To Target": deficit['Sales Driven Target'],
                    "Transfer Qty": transfer_qty,
                    "Reason": f"Sales velocity {deficit.get('Weekly_Sales_Rate', 'N/A')} units/week"
                })
                surplus['Surplus'] -= transfer_qty
                deficit['Deficit'] -= transfer_qty
                if deficit['Deficit'] <= 0:
                    deficit_items.remove(deficit)
            if surplus['Surplus'] <= 0:
                break
    
    return pd.DataFrame(transfer_pairs) if transfer_pairs else pd.DataFrame()

# ============================================
# PDF GENERATION
# ============================================

def generate_transfer_pdf(transfers_df, title):
    """Generate PDF for transfers"""
    
    if transfers_df.empty:
        return None
    
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, f"PRAGATHI SHOES - {title}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(40, 10, "From", 1)
    pdf.cell(40, 10, "To", 1)
    pdf.cell(45, 10, "Product", 1)
    pdf.cell(20, 10, "Size", 1)
    pdf.cell(25, 10, "Qty", 1)
    pdf.cell(30, 10, "Reason", 1)
    pdf.ln()
    
    pdf.set_font("Arial", size=8)
    for _, row in transfers_df.iterrows():
        pdf.cell(40, 8, clean_text(row['From Branch'])[:38], 1)
        pdf.cell(40, 8, clean_text(row['To Branch'])[:38], 1)
        pdf.cell(45, 8, clean_text(row['Product'])[:43], 1)
        pdf.cell(20, 8, clean_text(row['Size'])[:18], 1)
        pdf.cell(25, 8, str(int(row['Transfer Qty'])), 1)
        pdf.cell(30, 8, clean_text(row['Reason'])[:28], 1)
        pdf.ln()
    
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# ============================================
# MAIN APP
# ============================================

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.subheader("Safety Stock Levels")
    safety_stock = st.number_input("Minimum Safety Stock (units)", value=6, min_value=1, max_value=20)
    for branch in BRANCHES.keys():
        if branch != "PRAGATHI SHOES":
            BRANCHES[branch]["min"] = safety_stock
    
    st.subheader("Sales Analysis Period")
    sales_period = st.selectbox("Sales Data Period", ["Last 30 Days", "Last 60 Days", "Last 90 Days", "All Data"], index=0)
    
    st.divider()
    
    st.subheader("📁 Upload Files")
    stock_file = st.file_uploader("SCHOOL STOCK.csv", type=["csv"], key="stock")
    sales_file = st.file_uploader("Sales Data File (CSV)", type=["csv"], key="sales")

# Main content
if stock_file and sales_file:
    with st.spinner("Analyzing stock and sales data..."):
        # Process files
        complete_inventory, all_skus = process_stock_file(stock_file)
        sales_data, sales_meta = process_sales_file(sales_file)
        
        if complete_inventory is None:
            st.error("Could not parse stock file. Please check the format.")
            st.stop()
        
        if sales_data is None:
            st.error("Could not parse sales file. Please check the format.")
            st.stop()
        
        # Calculate transfers based on sales
        transfers_df = calculate_sales_driven_transfers(complete_inventory, sales_data, BRANCHES)
        
        # Create tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🚚 Smart Transfers", "📈 Sales Analytics", "🏪 Branch Details"])
        
        # ============================================
        # TAB 1: DASHBOARD
        # ============================================
        with tab1:
            st.subheader("🏢 Sales-Driven Inventory Dashboard")
            
            col1, col2, col3, col4 = st.columns(4)
            
            total_stock = sum([df['Quantity'].sum() for df in complete_inventory.values()])
            total_sales = sales_data['Sales_Qty'].sum() if not sales_data.empty else 0
            total_transfers = len(transfers_df)
            transfer_qty = transfers_df['Transfer Qty'].sum() if not transfers_df.empty else 0
            
            with col1:
                st.metric("Total Stock", f"{int(total_stock):,}")
            with col2:
                st.metric("Total Sales (Period)", f"{int(total_sales):,}")
            with col3:
                st.metric("Suggested Transfers", total_transfers)
            with col4:
                st.metric("Units to Transfer", int(transfer_qty))
            
            st.markdown("---")
            
            # Sales vs Stock comparison
            st.subheader("📊 Sales vs Stock Comparison")
            
            # Aggregate sales by product
            top_products = sales_data.groupby('Product')['Sales_Qty'].sum().nlargest(10).reset_index()
            st.dataframe(top_products, use_container_width=True)
        
        # ============================================
        # TAB 2: SMART TRANSFERS
        # ============================================
        with tab2:
            st.subheader("🚚 Sales-Driven Transfer Recommendations")
            st.markdown("**Transfers are based on sales velocity, not just arbitrary targets**")
            
            if not transfers_df.empty:
                # Sort by priority (high demand deficit first)
                transfers_df = transfers_df.sort_values('Transfer Qty', ascending=False)
                
                st.dataframe(transfers_df, use_container_width=True)
                
                # Generate PDF
                if st.button("📄 Generate Transfer Order PDF"):
                    pdf_data = generate_transfer_pdf(transfers_df, "SALES_DRIVEN_TRANSFERS")
                    if pdf_data:
                        st.download_button("✅ Download PDF", pdf_data, f"smart_transfers_{datetime.now().strftime('%Y%m%d')}.pdf")
            else:
                st.success("✅ No transfers needed based on current sales data!")
        
        # ============================================
        # TAB 3: SALES ANALYTICS
        # ============================================
        with tab3:
            st.subheader("📈 Sales Analytics")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Top Selling Products**")
                top_selling = sales_data.nlargest(10, 'Sales_Qty')[['Product', 'Sales_Qty']]
                st.dataframe(top_selling, use_container_width=True)
            
            with col2:
                st.markdown("**Sales by Branch**")
                if 'Branch' in sales_data.columns:
                    branch_sales = sales_data.groupby('Branch')['Sales_Qty'].sum().reset_index()
                    st.dataframe(branch_sales, use_container_width=True)
                else:
                    st.info("Branch information not available in sales file")
            
            st.markdown("---")
            
            st.subheader("📊 Demand Forecasting")
            st.markdown("**Products with high weekly sales velocity**")
            
            if 'Weekly_Sales_Rate' in sales_data.columns:
                high_velocity = sales_data[sales_data['Weekly_Sales_Rate'] > 10].nlargest(10, 'Weekly_Sales_Rate')[['Product', 'Weekly_Sales_Rate', 'Sales_Qty']]
                high_velocity.columns = ['Product', 'Weekly Demand', 'Total Sales']
                st.dataframe(high_velocity, use_container_width=True)
        
        # ============================================
        # TAB 4: BRANCH DETAILS
        # ============================================
        with tab4:
            st.subheader("🏪 Branch-wise Analysis")
            
            selected_branch = st.selectbox("Select Branch", [BRANCHES[b]['name'] for b in BRANCH_ORDER if b != "PRAGATHI SHOES"])
            
            # Find branch key
            branch_key = None
            for b in BRANCH_ORDER:
                if BRANCHES[b]['name'] == selected_branch:
                    branch_key = b
                    break
            
            if branch_key:
                branch_df = complete_inventory[branch_key]
                config = BRANCHES[branch_key]
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Current Stock", int(branch_df['Quantity'].sum()))
                with col2:
                    st.metric("SKUs", len(branch_df))
                with col3:
                    zero_count = len(branch_df[branch_df['Quantity'] == 0])
                    st.metric("Zero Stock SKUs", zero_count)
                
                st.markdown("---")
                
                # Show inventory
                st.subheader("Current Inventory")
                display_df = branch_df[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                display_df = display_df.sort_values(['Product', 'Size'])
                st.dataframe(display_df, use_container_width=True)

else:
    st.info("👈 **Upload both files: SCHOOL STOCK.csv AND Sales Data CSV**")
    
    st.markdown("""
    ## 📦 Sales-Driven Stock Transfer System
    
    ### How It Works:
    
    1. **Upload Stock File** - Your SCHOOL STOCK.csv
    2. **Upload Sales File** - Any CSV with sales data
    3. **System Analyzes** - Combines stock + sales data
    4. **Smart Transfers** - Based on actual demand, not arbitrary targets
    
    ### Sales File Format:
    
    The system automatically detects these columns:
    - **Product/Item/SKU** - Product identifier
    - **Quantity/Qty/Sold** - Number of units sold
    - **Branch/Store** (optional) - Branch name
    - **Date** (optional) - For velocity calculation
    
    ### Key Features:
    
    | Feature | Description |
    |---------|-------------|
    | **Demand-Based Targets** | Targets adjust based on sales velocity |
    | **Sales Velocity** | Calculates daily/weekly/monthly sales rates |
    | **Smart Transfer Logic** | Stock moves to high-demand branches |
    | **Zero Stock Detection** | Identifies complete stockouts |
    | **PDF Generation** | Professional transfer orders |
    
    ### The Intelligence:
    
    - **Fast-moving products** get higher stock targets
    - **Slow-moving products** get lower targets
    - **Branches with high sales** receive priority
    - **Branches with low sales** send surplus
    """)

st.sidebar.markdown("---")
st.sidebar.caption("v6.0 | Sales-Driven Intelligent Distribution")
