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

# Order of branches for display
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
        
        # Create tabs
        tab_names = ["📊 Master Dashboard", "🚚 All Transfers (Branch Wise)"] + [f"🏪 {BRANCHES[b]['name']}" for b in BRANCH_ORDER]
        tabs = st.tabs(tab_names)
        
        # ============================================
        # TAB 0: MASTER DASHBOARD
        # ============================================
        with tabs[0]:
            st.subheader("🏢 Complete Inventory Overview")
            
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            
            total_stock = 0
            total_skus = len(all_skus)
            for branch, df in complete_inventory.items():
                total_stock += df['Quantity'].sum()
            
            total_transfers = len(transfers_df)
            total_transfer_qty = transfers_df['Transfer Qty'].sum() if not transfers_df.empty else 0
            
            with col1:
                st.metric("Total SKUs", total_skus)
            with col2:
                st.metric("Total Stock", f"{int(total_stock):,}")
            with col3:
                st.metric("Suggested Transfers", total_transfers)
            with col4:
                st.metric("Units to Transfer", int(total_transfer_qty))
            
            st.markdown("---")
            
            # Branch-wise stock summary with shortages
            st.subheader("📊 Branch Stock Summary (with Shortages)")
            
            branch_summary = []
            for branch in BRANCH_ORDER:
                df = complete_inventory[branch]
                config = BRANCHES[branch]
                
                total_qty = df['Quantity'].sum()
                target_total = config['target'] * len(df)
                shortage = max(0, target_total - total_qty)
                surplus = max(0, total_qty - target_total)
                
                # Count SKUs with zero stock
                zero_stock_skus = len(df[df['Quantity'] == 0])
                skus_needed = len(df[df['Quantity'] < config['min']])
                
                branch_summary.append({
                    "Branch": config['name'],
                    "Total Stock": int(total_qty),
                    "Target": int(target_total),
                    "Shortage": int(shortage),
                    "Surplus": int(surplus),
                    "Zero Stock SKUs": zero_stock_skus,
                    "SKUs Needing Stock": skus_needed,
                    "Total SKUs": len(df)
                })
            
            st.dataframe(pd.DataFrame(branch_summary), use_container_width=True)
            
            # Show branches with zero stock items
            st.subheader("⚠️ Branches with Zero Stock Items")
            for branch in BRANCH_ORDER:
                df = complete_inventory[branch]
                zero_items = df[df['Quantity'] == 0]
                if not zero_items.empty:
                    with st.expander(f"{BRANCHES[branch]['name']} - {len(zero_items)} items out of stock"):
                        st.dataframe(zero_items[['Product', 'Size', 'Colour', 'Article', 'MRP']], use_container_width=True)
        
        # ============================================
        # TAB 1: ALL TRANSFERS (BRANCH WISE ORDERED)
        # ============================================
        with tabs[1]:
            st.subheader("🚚 All Suggested Transfers (Ordered by Source Branch)")
            
            if not transfers_df.empty:
                # Sort transfers by From Branch, then Product, Colour, Size, Article, MRP
                sorted_transfers = transfers_df.sort_values(
                    by=['From Branch', 'Product', 'Colour', 'Size', 'Article', 'MRP']
                )
                
                # Display with all required columns
                display_cols = ['From Branch', 'To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                st.dataframe(sorted_transfers[display_cols], use_container_width=True)
                
                # Download all transfers
                csv = sorted_transfers[display_cols].to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download All Transfers (CSV)", csv, f"all_transfers_{datetime.now().strftime('%Y%m%d')}.csv")
                
                # Group by source branch for better visualization
                st.subheader("📦 Transfers Grouped by Source Branch")
                for branch in BRANCH_ORDER:
                    branch_outgoing = transfers_df[transfers_df['From Branch'] == branch]
                    if not branch_outgoing.empty:
                        with st.expander(f"📤 From: {BRANCHES[branch]['name']} ({len(branch_outgoing)} items)"):
                            display_out = branch_outgoing.sort_values(['Product', 'Colour', 'Size', 'Article'])[
                                ['To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                            ]
                            st.dataframe(display_out, use_container_width=True)
            else:
                st.success("✅ No transfers needed! All branches are optimally stocked.")
        
        # ============================================
        # BRANCH-SPECIFIC TABS
        # ============================================
        for idx, branch in enumerate(BRANCH_ORDER):
            with tabs[idx + 2]:
                config = BRANCHES[branch]
                branch_df = complete_inventory[branch]
                
                st.subheader(f"🏪 {config['name']} - Complete Stock Analysis")
                
                # Metrics
                col1, col2, col3, col4 = st.columns(4)
                total_stock = int(branch_df['Quantity'].sum())
                sku_count = len(branch_df)
                zero_count = len(branch_df[branch_df['Quantity'] == 0])
                low_count = len(branch_df[(branch_df['Quantity'] > 0) & (branch_df['Quantity'] < config['min'])])
                
                with col1:
                    st.metric("Total Stock", total_stock)
                with col2:
                    st.metric("SKUs Carried", sku_count)
                with col3:
                    st.metric("Zero Stock SKUs", zero_count, delta="Need stock" if zero_count > 0 else None)
                with col4:
                    st.metric("Low Stock SKUs", low_count, delta="Need replenishment" if low_count > 0 else None)
                
                st.markdown("---")
                
                # Show complete inventory with status
                st.subheader("📋 Complete Inventory (Including Zero Stock)")
                display_df = branch_df[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                display_df['Status'] = display_df['Quantity'].apply(
                    lambda x: '🔴 ZERO' if x == 0 else ('🟡 LOW' if x < config['min'] else ('🟢 OK' if x <= config['target'] else '📤 SURPLUS'))
                )
                display_df = display_df.sort_values(['Product', 'Colour', 'Size', 'Article'])
                st.dataframe(display_df, use_container_width=True)
                
                # Show items needing stock (zero or low)
                needs_stock = branch_df[(branch_df['Quantity'] == 0) | (branch_df['Quantity'] < config['min'])]
                if not needs_stock.empty:
                    st.subheader("⚠️ Items Needing Stock")
                    needs_display = needs_stock[['Product', 'Size', 'Colour', 'Article', 'MRP', 'Quantity']].copy()
                    needs_display['Required'] = needs_display['Quantity'].apply(lambda x: config['target'] - x)
                    st.dataframe(needs_display, use_container_width=True)
                
                # Show transfers for this branch
                outgoing = transfers_df[transfers_df['From Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                incoming = transfers_df[transfers_df['To Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**📤 STOCK TO SEND (Surplus)**")
                    if not outgoing.empty:
                        outgoing_display = outgoing.sort_values(['Product', 'Colour', 'Size', 'Article'])[
                            ['To Branch', 'Product', 'Size', 'Colour', 'Article', 'MRP', 'Transfer Qty']
                        ]
                        st.dataframe(outgoing_display, use_container_width=True)
                    else:
                        st.info("No surplus to send")
                
                with col2:
                    st.markdown("**📥 STOCK TO RECEIVE (Deficit)**")
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
    | **Zero Stock Tracking** | SKUs with 0 stock are shown as needing stock |
    | **Branch-wise Transfers** | All transfers grouped by source branch |
    | **Ordered Display** | Sorted by Product, Colour, Size, Article, MRP |
    | **Warehouse Included** | Warehouse can send/receive transfers |
    | **Complete Details** | Shows Article No., MRP, Size, Colour |
    | **PDF Generation** | Branch-specific transfer orders |
    
    ### How It Works:
    
    1. **Upload CSV** - System reads all branches including warehouse
    2. **Set Targets** - Configure individual branch targets in sidebar
    3. **Auto Analysis** - Identifies surplus and deficit branches
    4. **Zero Stock Detection** - SKUs with 0 stock are flagged
    5. **Smart Matching** - Surplus matched to deficit by exact SKU
    6. **Ordered Output** - All transfers sorted by branch and product details
    
    ### Transfer Logic:
    - Every SKU is tracked across ALL branches
    - Branches with stock > target = SURPLUS (send out)
    - Branches with stock < target = DEFICIT (receive)
    - Warehouse can both send and receive
    - Zero stock SKUs are prioritized for receiving
    """)

st.sidebar.markdown("---")
st.sidebar.caption("v4.0 | Complete Transfer System with Zero Stock Tracking")
