import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import re

st.set_page_config(page_title="Pragathi Shoes - Complete Transfer System", layout="wide")

st.title("👞 Pragathi Shoes - Complete Stock Transfer System")
st.markdown("**Intelligent surplus redistribution across all branches including warehouse**")

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
    """Remove special characters for PDF"""
    if pd.isna(text):
        return ""
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)
    text = text.replace('→', '->')
    text = text.replace('✓', '')
    text = text.replace('✅', '')
    text = text.replace('⚠️', '')
    text = text.replace('🔴', '')
    text = text.replace('🟢', '')
    text = text.replace('🟡', '')
    return text.strip()

# ============================================
# DATA PROCESSING
# ============================================

def process_inventory_file(uploaded_file):
    """Parse uploaded CSV and organize by branch"""
    
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
    
    # Get unique SKUs across all branches
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    all_skus = df_items['SKU'].unique()
    
    # Create complete inventory matrix (all branches x all SKUs)
    complete_inventory = {}
    
    for branch in BRANCHES.keys():
        branch_data = df_items[df_items['Branch'] == branch] if branch in df_items['Branch'].values else pd.DataFrame()
        
        # Create a dictionary of SKU -> Quantity for this branch
        sku_dict = {}
        if not branch_data.empty:
            for _, row in branch_data.iterrows():
                sku_dict[row['SKU']] = row['Quantity']
        
        # For each SKU, ensure we have a record (0 if not present)
        branch_records = []
        for sku in all_skus:
            # Get SKU details from any branch that has it
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

def calculate_all_transfers(complete_inventory, branches_config):
    """Calculate transfers between ALL branches including warehouse"""
    
    all_transfers = []
    
    # Get all SKUs
    first_branch = next(iter(complete_inventory.values()))
    if first_branch.empty:
        return pd.DataFrame()
    
    all_skus = first_branch['SKU'].unique()
    
    for sku in all_skus:
        # Get current stock for each branch
        branch_stock = {}
        sku_details = {}
        
        for branch, df in complete_inventory.items():
            sku_row = df[df['SKU'] == sku]
            if not sku_row.empty:
                quantity = sku_row['Quantity'].iloc[0]
                branch_stock[branch] = quantity
                if not sku_details:
                    sku_details = {
                        "Product": sku_row['Product'].iloc[0],
                        "Colour": sku_row['Colour'].iloc[0],
                        "Size": sku_row['Size'].iloc[0],
                        "Article": sku_row['Article'].iloc[0],
                        "MRP": sku_row['MRP'].iloc[0]
                    }
            else:
                branch_stock[branch] = 0
        
        if not sku_details:
            continue
        
        # Calculate surplus and deficit for ALL branches
        branch_status = []
        for branch, stock in branch_stock.items():
            target = branches_config[branch]["target"]
            if stock > target:
                surplus = stock - target
                branch_status.append({
                    "branch": branch, 
                    "status": "surplus", 
                    "current": stock, 
                    "target": target,
                    "difference": surplus
                })
            elif stock < target:
                needed = target - stock
                branch_status.append({
                    "branch": branch, 
                    "status": "deficit", 
                    "current": stock, 
                    "target": target,
                    "difference": needed
                })
        
        # Sort: surplus first, then deficit
        surplus_branches = [b for b in branch_status if b["status"] == "surplus"]
        deficit_branches = [b for b in branch_status if b["status"] == "deficit"]
        
        # Match surplus to deficit
        for surplus in surplus_branches:
            remaining_surplus = surplus["difference"]
            
            for deficit in deficit_branches[:]:
                if remaining_surplus <= 0:
                    break
                
                transfer_qty = min(remaining_surplus, deficit["difference"])
                
                if transfer_qty > 0:
                    all_transfers.append({
                        "SKU": sku,
                        "Product": sku_details['Product'],
                        "Colour": sku_details['Colour'],
                        "Size": sku_details['Size'],
                        "Article": sku_details['Article'],
                        "MRP": sku_details['MRP'],
                        "From Branch": surplus["branch"],
                        "From Current": surplus["current"],
                        "From Target": surplus["target"],
                        "To Branch": deficit["branch"],
                        "To Current": deficit["current"],
                        "To Target": deficit["target"],
                        "Transfer Qty": transfer_qty,
                        "After Transfer From": surplus["current"] - transfer_qty,
                        "After Transfer To": deficit["current"] + transfer_qty
                    })
                    
                    remaining_surplus -= transfer_qty
                    deficit["difference"] -= transfer_qty
                    
                    if deficit["difference"] <= 0:
                        deficit_branches.remove(deficit)
    
    return pd.DataFrame(all_transfers) if all_transfers else pd.DataFrame()

def get_products_with_no_stock_anywhere(complete_inventory):
    """Find products that have zero stock in ALL branches"""
    
    all_skus_data = []
    
    # Get all unique SKUs from any branch
    first_branch = next(iter(complete_inventory.values()))
    if first_branch.empty:
        return pd.DataFrame()
    
    all_skus = first_branch['SKU'].unique()
    
    for sku in all_skus:
        # Check stock across all branches
        total_stock = 0
        sku_info = None
        
        for branch, df in complete_inventory.items():
            sku_row = df[df['SKU'] == sku]
            if not sku_row.empty:
                quantity = sku_row['Quantity'].iloc[0]
                total_stock += quantity
                if sku_info is None:
                    sku_info = {
                        "Product": sku_row['Product'].iloc[0],
                        "Colour": sku_row['Colour'].iloc[0],
                        "Size": sku_row['Size'].iloc[0],
                        "Article": sku_row['Article'].iloc[0],
                        "MRP": sku_row['MRP'].iloc[0]
                    }
        
        if total_stock == 0 and sku_info:
            all_skus_data.append(sku_info)
    
    return pd.DataFrame(all_skus_data)

def get_branch_transfers(transfers_df, branch_name, transfer_type="all"):
    """Get transfers for a specific branch"""
    if transfers_df.empty:
        return pd.DataFrame()
    
    if transfer_type == "outgoing":
        return transfers_df[transfers_df['From Branch'] == branch_name].copy()
    elif transfer_type == "incoming":
        return transfers_df[transfers_df['To Branch'] == branch_name].copy()
    else:
        outgoing = transfers_df[transfers_df['From Branch'] == branch_name].copy()
        incoming = transfers_df[transfers_df['To Branch'] == branch_name].copy()
        return pd.concat([outgoing, incoming]) if not outgoing.empty or not incoming.empty else pd.DataFrame()

# ============================================
# PDF GENERATION
# ============================================

def generate_branch_transfer_pdf(transfers_df, branch_name, branch_config):
    """Generate PDF for branch-specific transfers"""
    
    if transfers_df.empty:
        return None
    
    branch_name_clean = clean_text(branch_config['name'])
    
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, "PRAGATHI SHOES - STOCK TRANSFER ORDER", ln=True, align='C')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, f"Branch: {branch_name_clean}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
    pdf.ln(10)
    
    # Separate outgoing and incoming
    outgoing = transfers_df[transfers_df['From Branch'] == branch_name]
    incoming = transfers_df[transfers_df['To Branch'] == branch_name]
    
    if not outgoing.empty:
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(200, 10, "STOCK TO SEND (SURPLUS)", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(40, 10, "Send To", 1)
        pdf.cell(50, 10, "Product", 1)
        pdf.cell(20, 10, "Size", 1)
        pdf.cell(25, 10, "Colour", 1)
        pdf.cell(30, 10, "Article", 1)
        pdf.cell(20, 10, "MRP", 1)
        pdf.cell(15, 10, "Qty", 1)
        pdf.ln()
        
        pdf.set_font("Arial", size=8)
        for _, row in outgoing.iterrows():
            pdf.cell(40, 8, clean_text(row['To Branch'])[:38], 1)
            pdf.cell(50, 8, clean_text(row['Product'])[:48], 1)
            pdf.cell(20, 8, clean_text(row['Size'])[:18], 1)
            pdf.cell(25, 8, clean_text(row['Colour'])[:23], 1)
            pdf.cell(30, 8, clean_text(row['Article'])[:28], 1)
            pdf.cell(20, 8, clean_text(row['MRP'])[:18], 1)
            pdf.cell(15, 8, str(int(row['Transfer Qty'])), 1)
            pdf.ln()
        pdf.ln(5)
    
    if not incoming.empty:
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(200, 10, "STOCK TO RECEIVE (DEFICIT)", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(40, 10, "Receive From", 1)
        pdf.cell(50, 10, "Product", 1)
        pdf.cell(20, 10, "Size", 1)
        pdf.cell(25, 10, "Colour", 1)
        pdf.cell(30, 10, "Article", 1)
        pdf.cell(20, 10, "MRP", 1)
        pdf.cell(15, 10, "Qty", 1)
        pdf.ln()
        
        pdf.set_font("Arial", size=8)
        for _, row in incoming.iterrows():
            pdf.cell(40, 8, clean_text(row['From Branch'])[:38], 1)
            pdf.cell(50, 8, clean_text(row['Product'])[:48], 1)
            pdf.cell(20, 8, clean_text(row['Size'])[:18], 1)
            pdf.cell(25, 8, clean_text(row['Colour'])[:23], 1)
            pdf.cell(30, 8, clean_text(row['Article'])[:28], 1)
            pdf.cell(20, 8, clean_text(row['MRP'])[:18], 1)
            pdf.cell(15, 8, str(int(row['Transfer Qty'])), 1)
            pdf.ln()
    
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 9)
    pdf.cell(200, 5, "Authorized Signatory: ____________________", ln=True)
    pdf.cell(200, 5, "Warehouse Manager", ln=True)
    
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# ============================================
# MAIN APP
# ============================================

# Sidebar
with st.sidebar:
    st.header("⚙️ Branch Configuration")
    
    st.subheader("Set Individual Branch Targets")
    for branch in BRANCH_ORDER:
        if branch != "PRAGATHI SHOES":
            default = BRANCHES[branch]["target"]
            BRANCHES[branch]["target"] = st.number_input(
                f"{BRANCHES[branch]['name']}", 
                value=default, 
                min_value=1, 
                max_value=50,
                key=f"target_{branch}"
            )
    
    st.subheader("Warehouse Configuration")
    BRANCHES["PRAGATHI SHOES"]["target"] = st.number_input(
        "Central Warehouse", 
        value=20, 
        min_value=5, 
        max_value=100,
        key="target_warehouse"
    )
    
    st.divider()
    uploaded_file = st.file_uploader("📁 Upload SCHOOL STOCK.csv", type=["csv"])

# Main content
if uploaded_file:
    with st.spinner("Analyzing inventory across all branches including warehouse..."):
        complete_inventory, all_skus = process_inventory_file(uploaded_file)
        
        if complete_inventory is None:
            st.error("Could not parse the file. Please check the format.")
            st.stop()
        
        # Calculate all transfers
        transfers_df = calculate_all_transfers(complete_inventory, BRANCHES)
        
        # Get products with no stock anywhere
        no_stock_anywhere = get_products_with_no_stock_anywhere(complete_inventory)
        
        # Create tabs
        tab_names = ["📊 Master Dashboard", "🚚 All Transfers", "⚠️ Zero Stock Anywhere"] + [f"🏪 {BRANCHES[b]['name']}" for b in BRANCH_ORDER]
        tabs = st.tabs(tab_names)
        
        # ============================================
        # TAB 0: MASTER DASHBOARD
        # ============================================
        with tabs[0]:
            st.subheader("🏢 Complete Inventory Overview")
            
            # Summary metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            
            total_stock = 0
            total_skus = len(all_skus)
            for branch, df in complete_inventory.items():
                total_stock += df['Quantity'].sum()
            
            total_transfers = len(transfers_df)
            total_transfer_qty = transfers_df['Transfer Qty'].sum() if not transfers_df.empty else 0
            total_no_stock = len(no_stock_anywhere)
            
            with col1:
                st.metric("Total SKUs", total_skus)
            with col2:
                st.metric("Total Stock", f"{int(total_stock):,}")
            with col3:
                st.metric("Suggested Transfers", total_transfers)
            with col4:
                st.metric("Units to Transfer", int(total_transfer_qty))
            with col5:
                st.metric("Zero Stock Anywhere", total_no_stock, delta="URGENT" if total_no_stock > 0 else None)
            
            st.markdown("---")
            
            # Branch-wise stock summary
            st.subheader("📊 Branch Stock Summary")
            
            branch_summary = []
            for branch in BRANCH_ORDER:
                df = complete_inventory[branch]
                config = BRANCHES[branch]
                
                total_qty = df['Quantity'].sum()
                target_total = config['target'] * len(df)
                shortage = max(0, target_total - total_qty)
                surplus = max(0, total_qty - target_total)
                
                zero_stock_skus = len(df[df['Quantity'] == 0])
                low_stock_skus = len(df[(df['Quantity'] > 0) & (df['Quantity'] < config['min'])])
                
                branch_summary.append({
                    "Branch": config['name'],
                    "Total Stock": int(total_qty),
                    "Target": int(target_total),
                    "Shortage": int(shortage),
                    "Surplus": int(surplus),
                    "Zero Stock": zero_stock_skus,
                    "Low Stock": low_stock_skus
                })
            
            st.dataframe(pd.DataFrame(branch_summary), use_container_width=True)
        
        # ============================================
        # TAB 1: ALL TRANSFERS
        # ============================================
        with tabs[1]:
            st.subheader("🚚 All Suggested Transfers (Ordered by Source Branch)")
            
            if not transfers_df.empty:
                sorted_transfers = transfers_df.sort_values(
                    by=['From Branch', 'Product', 'Colour', 'Size', 'Article', 'MRP']
                )
                
                display_cols = ['From Branch', 'To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                st.dataframe(sorted_transfers[display_cols], use_container_width=True)
                
                csv = sorted_transfers[display_cols].to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download All Transfers (CSV)", csv, f"all_transfers_{datetime.now().strftime('%Y%m%d')}.csv")
            else:
                st.success("✅ No transfers needed!")
        
        # ============================================
        # TAB 2: ZERO STOCK ANYWHERE
        # ============================================
        with tabs[2]:
            st.subheader("⚠️ Products with ZERO Stock Across ALL Branches")
            st.markdown("**These products are completely out of stock in every branch including warehouse**")
            
            if not no_stock_anywhere.empty:
                st.error(f"🚨 {len(no_stock_anywhere)} products have ZERO stock anywhere!")
                
                # Add required quantity column (based on target for each branch)
                no_stock_display = no_stock_anywhere.copy()
                
                # Calculate total required across all branches
                required_qty = []
                for _, row in no_stock_display.iterrows():
                    total_needed = 0
                    for branch in BRANCH_ORDER:
                        if branch != "PRAGATHI SHOES":
                            total_needed += BRANCHES[branch]["target"]
                    required_qty.append(total_needed)
                
                no_stock_display['Required Quantity (All Branches)'] = required_qty
                no_stock_display['Urgency'] = 'HIGH - Complete Out of Stock'
                
                st.dataframe(no_stock_display, use_container_width=True)
                
                # Export
                csv = no_stock_display.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Zero Stock Report", csv, f"zero_stock_anywhere_{datetime.now().strftime('%Y%m%d')}.csv")
                
                # Show which branches need these items
                st.subheader("🏪 Branches That Need These Products")
                for _, row in no_stock_display.iterrows():
                    with st.expander(f"{row['Product']} - Size {row['Size']} - {row['Colour']}"):
                        needs_info = []
                        for branch in BRANCH_ORDER:
                            if branch != "PRAGATHI SHOES":
                                needs_info.append({
                                    "Branch": BRANCHES[branch]['name'],
                                    "Target": BRANCHES[branch]["target"],
                                    "Current": 0,
                                    "Required": BRANCHES[branch]["target"]
                                })
                        st.dataframe(pd.DataFrame(needs_info), use_container_width=True)
            else:
                st.success("✅ All products have stock in at least one branch!")
        
        # ============================================
        # BRANCH-SPECIFIC TABS
        # ============================================
        for idx, branch in enumerate(BRANCH_ORDER):
            with tabs[idx + 3]:
                config = BRANCHES[branch]
                branch_df = complete_inventory[branch]
                
                st.subheader(f"🏪 {config['name']} - Complete Stock Analysis")
                
                # Metrics row
                col1, col2, col3, col4, col5 = st.columns(5)
                total_stock = int(branch_df['Quantity'].sum())
                sku_count = len(branch_df)
                zero_count = len(branch_df[branch_df['Quantity'] == 0])
                low_count = len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < config['min'])])
                surplus_count = len(branch_df[branch_df['Quantity'] > config['target']])
                
                with col1:
                    st.metric("Total Stock", total_stock)
                with col2:
                    st.metric("Total SKUs", sku_count)
                with col3:
                    st.metric("Zero Stock", zero_count, delta="URGENT" if zero_count > 0 else None)
                with col4:
                    st.metric("Low Stock", low_count, delta="Needs attention" if low_count > 0 else None)
                with col5:
                    st.metric("Surplus", surplus_count, delta="Can share" if surplus_count > 0 else None)
                
                st.markdown("---")
                
                # TABLE 1: Zero Stock Items (Quantity = 0)
                st.subheader("📋 TABLE 1: ZERO STOCK ITEMS")
                zero_stock = branch_df[branch_df['Quantity'] == 0]
                if not zero_stock.empty:
                    st.warning(f"⚠️ {len(zero_stock)} items have ZERO stock!")
                    zero_display = zero_stock[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                    zero_display['Required'] = config['target']
                    st.dataframe(zero_display, use_container_width=True)
                else:
                    st.success("✅ No zero stock items in this branch!")
                
                st.markdown("---")
                
                # TABLE 2: Low Stock Items (0 < Quantity < min)
                st.subheader("📋 TABLE 2: LOW STOCK ITEMS")
                low_stock = branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < config['min'])]
                if not low_stock.empty:
                    st.warning(f"⚠️ {len(low_stock)} items have LOW stock (below {config['min']} units)!")
                    low_display = low_stock[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                    low_display['Current'] = low_display['Quantity']
                    low_display['Minimum Required'] = config['min']
                    low_display['Target'] = config['target']
                    low_display['Additional Needed'] = config['target'] - low_display['Quantity']
                    st.dataframe(low_display, use_container_width=True)
                else:
                    st.success(f"✅ No low stock items (all above {config['min']} units)!")
                
                st.markdown("---")
                
                # TABLE 3: Complete Inventory
                st.subheader("📋 TABLE 3: COMPLETE INVENTORY")
                display_df = branch_df[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                display_df['Status'] = display_df['Quantity'].apply(
                    lambda x: '🔴 ZERO' if x == 0 else ('🟡 LOW' if x < config['min'] else ('🟢 OK' if x <= config['target'] else '📤 SURPLUS'))
                )
                display_df = display_df.sort_values(['Product', 'Colour', 'Size', 'Article'])
                st.dataframe(display_df, use_container_width=True)
                
                st.markdown("---")
                
                # Show transfers for this branch
                outgoing = transfers_df[transfers_df['From Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                incoming = transfers_df[transfers_df['To Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("📤 STOCK TO SEND (Surplus)")
                    if not outgoing.empty:
                        outgoing_display = outgoing.sort_values(['Product', 'Colour', 'Size', 'Article'])[
                            ['To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                        ]
                        st.dataframe(outgoing_display, use_container_width=True)
                    else:
                        st.info("No surplus to send")
                
                with col2:
                    st.subheader("📥 STOCK TO RECEIVE (Deficit)")
                    if not incoming.empty:
                        incoming_display = incoming.sort_values(['Product', 'Colour', 'Size', 'Article'])[
                            ['From Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                        ]
                        st.dataframe(incoming_display, use_container_width=True)
                    else:
                        st.info("No incoming transfers needed")
                
                # Generate PDF
                branch_all_transfers = get_branch_transfers(transfers_df, branch, "all")
                if not branch_all_transfers.empty:
                    st.markdown("---")
                    if st.button(f"📄 Generate Transfer Order PDF", key=f"pdf_{branch}"):
                        branch_pdf = generate_branch_transfer_pdf(branch_all_transfers, branch, config)
                        if branch_pdf:
                            st.download_button(
                                "✅ Download PDF", 
                                branch_pdf, 
                                f"{branch.replace(' ', '_')}_transfer_order_{datetime.now().strftime('%Y%m%d')}.pdf"
                            )

else:
    # Instructions
    st.info("👈 **Upload your SCHOOL STOCK.csv file using the sidebar**")
    
    st.markdown("""
    ## 📦 Complete Stock Transfer System
    
    ### Features Included:
    
    | Feature | Description |
    |---------|-------------|
    | **Zero Stock Table** | Shows items with 0 quantity in each branch |
    | **Low Stock Table** | Shows items below minimum threshold |
    | **Zero Stock Anywhere** | Products completely out of stock across all branches |
    | **Required Quantity** | Calculates how many units needed |
    | **Branch-wise Transfers** | All transfers grouped by source branch |
    | **Complete Details** | Shows Product, Size, Colour, Article, MRP |
    | **PDF Generation** | Branch-specific transfer orders |
    
    ### Branch Tabs Include 3 Tables:
    
    1. **TABLE 1: ZERO STOCK ITEMS** - Items with 0 quantity
    2. **TABLE 2: LOW STOCK ITEMS** - Items below minimum threshold  
    3. **TABLE 3: COMPLETE INVENTORY** - All items with status
    
    ### Global Zero Stock Tab:
    - Shows products with ZERO stock in ALL branches
    - Calculates total required quantity
    - Shows which branches need these products
    
    ### Transfer Logic:
    - Surplus branches (stock > target) send to deficit branches (stock < target)
    - Warehouse included in transfers
    - Exact SKU matching (Product + Colour + Size + Article + MRP)
    """)

st.sidebar.markdown("---")
st.sidebar.caption("v5.0 | Complete System with Zero Stock Tracking & Multiple Tables")
