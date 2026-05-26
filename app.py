import streamlit as st
import pandas as pd
import numpy as np
from fpdf import FPDF
from datetime import datetime
import io
import re

st.set_page_config(page_title="Pragathi Shoes - Branch Transfer System", layout="wide")

st.title("👞 Pragathi Shoes - Intelligent Stock Transfer System")
st.markdown("**Automated surplus redistribution across branches**")

# ============================================
# BRANCH CONFIGURATION
# ============================================

# Define branches and their target stock levels
BRANCHES = {
    "POPULAR SHOE COMPANY": {"target": 12, "min": 6, "name": "Popular Store"},
    "PRAGATHI SHOES AMD 2": {"target": 8, "min": 4, "name": "AMD 2 Store"},
    "PRAGATHI SHOES RAGOLU": {"target": 8, "min": 4, "name": "Ragolu Store"},
    "PRAGATHI SHOES BALAGA": {"target": 8, "min": 4, "name": "Balaga Store"},
    "PRAGATHI SHOES AKP": {"target": 8, "min": 4, "name": "AKP Store"},
    "PRAGATHI SHOES": {"target": 20, "min": 10, "name": "Central Warehouse"}
}

def clean_text(text):
    """Remove special characters that cause PDF issues"""
    if pd.isna(text):
        return ""
    # Remove emojis and special symbols
    text = str(text)
    text = re.sub(r'[^\x00-\x7F]+', '', text)  # Remove non-ASCII
    text = text.replace('→', '->')
    text = text.replace('✓', '')
    text = text.replace('✅', '')
    text = text.replace('⚠️', '')
    text = text.replace('🔴', '')
    text = text.replace('🟢', '')
    text = text.replace('🟡', '')
    text = text.replace('📊', '')
    text = text.replace('🏪', '')
    text = text.replace('🚚', '')
    text = text.replace('📋', '')
    text = text.replace('🔍', '')
    text = text.replace('📄', '')
    text = text.replace('⚙️', '')
    text = text.replace('📁', '')
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
        return None, None, None
    
    # Get unique SKUs
    df_items['SKU'] = df_items.apply(lambda x: f"{x['Product']}|{x['Colour']}|{x['Size']}|{x['Article']}|{x['MRP']}", axis=1)
    
    # Create branch-wise inventory matrix
    branch_inventory = {}
    for branch in BRANCHES.keys():
        if branch in df_items['Branch'].values:
            branch_data = df_items[df_items['Branch'] == branch].copy()
            branch_inventory[branch] = branch_data
        else:
            branch_inventory[branch] = pd.DataFrame(columns=df_items.columns)
    
    return df_items, branch_inventory, BRANCHES

def calculate_transfers(branch_inventory, branches_config):
    """Calculate optimal transfers between branches"""
    
    all_transfers = []
    
    # Get all unique SKUs across all branches
    all_skus = set()
    for branch, df in branch_inventory.items():
        if not df.empty:
            all_skus.update(df['SKU'].unique())
    
    for sku in all_skus:
        # Get current stock for each branch for this SKU
        branch_stock = {}
        for branch, df in branch_inventory.items():
            if not df.empty:
                match = df[df['SKU'] == sku]
                if not match.empty:
                    branch_stock[branch] = match['Quantity'].iloc[0]
                else:
                    branch_stock[branch] = 0
            else:
                branch_stock[branch] = 0
        
        # Get SKU details
        sku_details = {}
        for branch, df in branch_inventory.items():
            if not df.empty:
                match = df[df['SKU'] == sku]
                if not match.empty:
                    row = match.iloc[0]
                    sku_details = {
                        "Product": clean_text(row['Product']),
                        "Colour": clean_text(row['Colour']),
                        "Size": clean_text(row['Size']),
                        "Article": clean_text(row['Article']),
                        "MRP": clean_text(row['MRP'])
                    }
                    break
        
        if not sku_details:
            continue
        
        # Identify surplus branches
        surplus_branches = []
        for branch, stock in branch_stock.items():
            if branch != "PRAGATHI SHOES":
                target = branches_config[branch]["target"]
                if stock > target:
                    surplus = stock - target
                    surplus_branches.append({"branch": branch, "surplus": surplus, "current": stock})
        
        # Identify deficit branches
        deficit_branches = []
        for branch, stock in branch_stock.items():
            if branch != "PRAGATHI SHOES":
                target = branches_config[branch]["target"]
                if stock < target:
                    needed = target - stock
                    deficit_branches.append({"branch": branch, "needed": needed, "current": stock})
        
        # Match surplus to deficit
        for surplus in surplus_branches:
            if not deficit_branches:
                break
            
            remaining_surplus = surplus['surplus']
            
            for deficit in deficit_branches[:]:
                if remaining_surplus <= 0:
                    break
                
                transfer_qty = min(remaining_surplus, deficit['needed'])
                
                if transfer_qty > 0:
                    all_transfers.append({
                        "SKU": sku,
                        "Product": sku_details['Product'],
                        "Colour": sku_details['Colour'],
                        "Size": sku_details['Size'],
                        "Article": sku_details['Article'],
                        "MRP": sku_details['MRP'],
                        "From Branch": surplus['branch'],
                        "From Current": surplus['current'],
                        "To Branch": deficit['branch'],
                        "To Current": deficit['current'],
                        "Transfer Qty": transfer_qty,
                        "After Transfer From": surplus['current'] - transfer_qty,
                        "After Transfer To": deficit['current'] + transfer_qty,
                        "Reason": f"Transfer from {surplus['branch']} to {deficit['branch']}"
                    })
                    
                    remaining_surplus -= transfer_qty
                    deficit['needed'] -= transfer_qty
                    
                    if deficit['needed'] <= 0:
                        deficit_branches.remove(deficit)
            
            surplus['surplus'] = remaining_surplus
    
    return pd.DataFrame(all_transfers) if all_transfers else pd.DataFrame()

# ============================================
# PDF GENERATION - FIXED VERSION
# ============================================

def generate_transfer_pdf(transfers_df, branch_name):
    """Generate PDF for branch-specific transfers - FIXED for Unicode"""
    
    if transfers_df.empty:
        return None
    
    # Clean branch name
    branch_name = clean_text(branch_name)
    
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, "PRAGATHI SHOES - STOCK TRANSFER ORDER", ln=True, align='C')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, f"Branch: {branch_name}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
    pdf.ln(10)
    
    # Table header
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(30, 10, "Direction", 1)
    pdf.cell(25, 10, "Size", 1)
    pdf.cell(45, 10, "Product", 1)
    pdf.cell(25, 10, "Colour", 1)
    pdf.cell(20, 10, "Qty", 1)
    pdf.cell(40, 10, "Article", 1)
    pdf.ln()
    
    # Table data
    pdf.set_font("Arial", size=8)
    for _, row in transfers_df.iterrows():
        # Clean all text fields
        direction = f"{clean_text(row['From Branch'])} to {clean_text(row['To Branch'])}"
        product = clean_text(row['Product'])[:40]
        colour = clean_text(row['Colour'])[:20]
        size = clean_text(row['Size'])[:20]
        article = clean_text(row['Article'])[:35]
        qty = int(row['Transfer Qty'])
        
        pdf.cell(30, 8, direction, 1)
        pdf.cell(25, 8, size, 1)
        pdf.cell(45, 8, product, 1)
        pdf.cell(25, 8, colour, 1)
        pdf.cell(20, 8, str(qty), 1)
        pdf.cell(40, 8, article, 1)
        pdf.ln()
    
    pdf.ln(5)
    pdf.set_font("Arial", 'I', 9)
    pdf.cell(200, 5, "Authorized Signatory: ____________________", ln=True)
    pdf.cell(200, 5, "Warehouse Manager", ln=True)
    
    # Return PDF as bytes
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# ============================================
# MAIN APP
# ============================================

# Sidebar configuration
with st.sidebar:
    st.header("⚙️ Branch Configuration")
    
    st.subheader("Set Individual Branch Targets")
    custom_targets = {}
    for branch in ["POPULAR SHOE COMPANY", "PRAGATHI SHOES AMD 2", "PRAGATHI SHOES RAGOLU", 
                   "PRAGATHI SHOES BALAGA", "PRAGATHI SHOES AKP"]:
        default = BRANCHES[branch]["target"]
        custom_targets[branch] = st.number_input(
            f"{BRANCHES[branch]['name']}", 
            value=default, 
            min_value=1, 
            max_value=50,
            key=f"target_{branch}"
        )
        BRANCHES[branch]["target"] = custom_targets[branch]
    
    st.divider()
    uploaded_file = st.file_uploader("📁 Upload SCHOOL STOCK.csv", type=["csv"])

# Main content
if uploaded_file:
    with st.spinner("Analyzing inventory across all branches..."):
        df_items, branch_inventory, branches_config = process_inventory_file(uploaded_file)
        
        if df_items is None or df_items.empty:
            st.error("Could not parse the file. Please check the format.")
            st.stop()
        
        # Calculate transfers
        transfers_df = calculate_transfers(branch_inventory, branches_config)
        
        # Create tabs
        branch_tabs = [b for b in BRANCHES.keys() if b != "PRAGATHI SHOES"]
        tabs = st.tabs(["📊 Master Dashboard"] + [f"🏪 {BRANCHES[b]['name']}" for b in branch_tabs])
        
        # ============================================
        # TAB 0: MASTER DASHBOARD
        # ============================================
        with tabs[0]:
            st.subheader("🏢 Enterprise Inventory Overview")
            
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            total_stock = sum([branch_inventory[b]['Quantity'].sum() if not branch_inventory[b].empty else 0 for b in BRANCHES.keys()])
            total_transfers = len(transfers_df)
            total_transfer_qty = transfers_df['Transfer Qty'].sum() if not transfers_df.empty else 0
            
            with col1:
                st.metric("Total Stock (Units)", f"{int(total_stock):,}")
            with col2:
                st.metric("Suggested Transfers", total_transfers)
            with col3:
                st.metric("Units to Transfer", int(total_transfer_qty))
            with col4:
                active = len([b for b in BRANCHES.keys() if not branch_inventory[b].empty])
                st.metric("Active Branches", active)
            
            st.markdown("---")
            
            # Branch comparison
            st.subheader("📊 Branch Stock Comparison")
            branch_comparison = []
            for branch, config in BRANCHES.items():
                if branch != "PRAGATHI SHOES":
                    stock = branch_inventory[branch]['Quantity'].sum() if not branch_inventory[branch].empty else 0
                    sku_count = len(branch_inventory[branch]) if not branch_inventory[branch].empty else 0
                    target_total = config['target'] * sku_count if sku_count > 0 else 0
                    
                    branch_comparison.append({
                        "Branch": config['name'],
                        "Total Stock": int(stock),
                        "Target": int(target_total),
                        "SKUs": sku_count,
                        "Status": "Surplus" if stock > target_total else ("Deficit" if stock < target_total else "Balanced")
                    })
            
            st.dataframe(pd.DataFrame(branch_comparison), use_container_width=True)
            
            # All transfers summary
            if not transfers_df.empty:
                st.subheader("🚚 All Suggested Transfers")
                display_transfers = transfers_df[['Product', 'Size', 'Colour', 'From Branch', 'To Branch', 'Transfer Qty']].copy()
                st.dataframe(display_transfers, use_container_width=True)
                
                # Generate all transfers PDF
                all_pdf = generate_transfer_pdf(transfers_df, "ALL_BRANCHES")
                if all_pdf:
                    st.download_button(
                        "📄 Download Complete Transfer Order (PDF)", 
                        all_pdf, 
                        f"all_transfers_{datetime.now().strftime('%Y%m%d')}.pdf"
                    )
            else:
                st.success("✅ No transfers needed! All branches are optimally stocked.")
        
        # ============================================
        # BRANCH-SPECIFIC TABS
        # ============================================
        for idx, branch in enumerate(branch_tabs):
            with tabs[idx + 1]:
                config = BRANCHES[branch]
                st.subheader(f"🏪 {config['name']} - Stock Management")
                
                branch_df = branch_inventory[branch]
                
                if branch_df.empty:
                    st.info(f"No data available for {config['name']}")
                    continue
                
                # Metrics
                col1, col2, col3 = st.columns(3)
                total_stock = int(branch_df['Quantity'].sum())
                sku_count = len(branch_df)
                target_total = config['target'] * sku_count
                
                with col1:
                    st.metric("Current Stock", total_stock)
                with col2:
                    st.metric("SKUs Carried", sku_count)
                with col3:
                    if total_stock > target_total:
                        st.metric("Status", "Surplus", delta=f"+{total_stock - target_total}")
                    else:
                        st.metric("Status", "Status", delta=f"{total_stock - target_total}")
                
                st.markdown("---")
                
                # Current inventory
                st.subheader("📋 Current Inventory")
                display_df = branch_df[['Product', 'Colour', 'Size', 'Article', 'MRP', 'Quantity']].copy()
                display_df['Status'] = display_df['Quantity'].apply(
                    lambda x: 'Surplus' if x > config['target'] else ('Low' if x < config['min'] else 'OK')
                )
                st.dataframe(display_df, use_container_width=True)
                
                # Transfers for this branch
                outgoing = transfers_df[transfers_df['From Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                incoming = transfers_df[transfers_df['To Branch'] == branch] if not transfers_df.empty else pd.DataFrame()
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**SEND (Surplus to Others)**")
                    if not outgoing.empty:
                        outgoing_display = outgoing[['Product', 'Size', 'Colour', 'To Branch', 'Transfer Qty']].copy()
                        outgoing_display.columns = ['Product', 'Size', 'Colour', 'Send To', 'Quantity']
                        st.dataframe(outgoing_display, use_container_width=True)
                    else:
                        st.info("No surplus to send")
                
                with col2:
                    st.markdown("**RECEIVE (From Others)**")
                    if not incoming.empty:
                        incoming_display = incoming[['Product', 'Size', 'Colour', 'From Branch', 'Transfer Qty']].copy()
                        incoming_display.columns = ['Product', 'Size', 'Colour', 'Receive From', 'Quantity']
                        st.dataframe(incoming_display, use_container_width=True)
                    else:
                        st.info("No incoming transfers needed")
                
                # PDF generation
                branch_transfers = pd.concat([outgoing, incoming]) if not outgoing.empty or not incoming.empty else pd.DataFrame()
                
                if not branch_transfers.empty:
                    st.markdown("---")
                    if st.button(f"Generate Transfer Order PDF", key=f"pdf_{branch}"):
                        branch_pdf = generate_transfer_pdf(branch_transfers, config['name'])
                        if branch_pdf:
                            st.download_button(
                                "Download PDF", 
                                branch_pdf, 
                                f"{branch.replace(' ', '_')}_transfers_{datetime.now().strftime('%Y%m%d')}.pdf"
                            )
                
                # Product check
                st.markdown("---")
                st.subheader("Check Specific Product")
                
                products = branch_df['Product'].unique().tolist()
                if products:
                    selected_product = st.selectbox("Select Product", products, key=f"product_{branch}")
                    
                    if selected_product:
                        product_data = branch_df[branch_df['Product'] == selected_product]
                        
                        st.markdown("**Size-wise stock:**")
                        size_data = product_data[['Size', 'Colour', 'Quantity', 'Article']].copy()
                        size_data['Status'] = size_data['Quantity'].apply(
                            lambda x: 'Send' if x > config['target'] else ('Receive' if x < config['min'] else 'OK')
                        )
                        st.dataframe(size_data, use_container_width=True)

else:
    # Instructions
    st.info("👈 **Upload your SCHOOL STOCK.csv file using the sidebar**")
    
    st.markdown("""
    ## Intelligent Stock Transfer System
    
    ### How It Works:
    
    1. **Upload your CSV** - The system reads all branches
    2. **Set branch targets** - Customize stock levels per branch in sidebar
    3. **Auto-calculates transfers** - Surplus branches send to deficit branches
    4. **Branch-specific tabs** - View each branch's position
    5. **Generate transfer orders** - PDF for each branch
    
    ### Features:
    - Individual Branch Targets
    - Smart Transfer Logic (Surplus -> Deficit)
    - Size-wise Analysis
    - PDF Transfer Orders
    - Branch Tabs
    """)

st.sidebar.markdown("---")
st.sidebar.caption("v3.1 | Fixed Unicode Support")
