import streamlit as st
import requests
import base64
import tempfile
import os
import re

# ====== 你的百度OCR API Key和Secret Key（请替换为你自己的） ======
BAIDU_API_KEY = "UzKIvxgTbDumWvbSjVkY6tUO"
BAIDU_SECRET_KEY = "AcNQNbHIrrLwf6KRYaHKlskL328mnP6l"

# ====== 你的HubSpot Token（私有应用Token，建议用环境变量或st.secrets）======
HUBSPOT_TOKEN = "pat-na1-ccae1c29-5027-4d4b-bafd-486cd1a987ec"

# ====== 百度OCR识别函数 ======
def baidu_ocr(image_path, api_key, secret_key):
    # 获取access_token
    token_url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": api_key,
        "client_secret": secret_key
    }
    token = requests.post(token_url, params=params).json()["access_token"]

    # 读取图片并base64编码
    with open(image_path, "rb") as f:
        img_base64 = base64.b64encode(f.read()).decode()

    # 调用通用文字识别API
    ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={token}"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"image": img_base64}
    result = requests.post(ocr_url, headers=headers, data=data).json()
    return [item["words"] for item in result.get("words_result", [])]

# ====== 信息提取优化版 ======
def extract_info(text_lines):
    # 1. 过滤无关内容
    filtered = []
    for line in text_lines:
        line = line.strip()
        if not line or re.match(r'^\d{4}年|\d{2}:\d{2}', line):  # 时间戳
            continue
        if '已成为联系人' in line or '端到端加密' in line or '发送消息' in line:
            continue
        if line.startswith('XINHUI') or line.startswith('NEW ARRIVAL'):
            continue
        filtered.append(line)

    # 2. 联系人提取（优先顶部昵称，其次自我介绍）
    contact = ""
    if filtered:
        # 顶部昵称一般在第一行
        if re.match(r'^[A-Za-z0-9\.\s]+$', filtered[0]) and len(filtered[0]) < 30:
            contact = filtered[0].strip()
    if not contact:
        # 查找自我介绍
        for line in filtered:
            m = re.search(r'(?:is|I am|this is|me)\s*([A-Za-z0-9\. ]+)', line, re.I)
            if m:
                contact = m.group(1).strip()
                break

    # 3. 需求提取（客户主动表达的内容，合并为一句）
    # 只保留客户发的英文内容，去掉自己回复
    demand_keywords = [
        "door bell", "send me", "so i can pay", "you send", "need", "require", "looking for", "order", "quote", "price"
    ]
    demand_lines = []
    for line in filtered:
        l = line.lower()
        if any(kw in l for kw in demand_keywords) or l in ["hi"]:
            demand_lines.append(line)
    demand = ", ".join(demand_lines)

    # 其它字段如无则留空
    return {
        "联系人": contact,
        "电话": "",
        "国家": "",
        "产品型号": "",
        "需求": demand
    }

# ====== HubSpot同步函数（联系人+备注）======
def sync_to_hubspot(contact, phone, country, product, demand, raw_text):
    # 1. 创建/更新联系人
    url = "https://api.hubapi.com/crm/v3/objects/contacts"
    headers = {
        "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "properties": {
            "firstname": contact,
            "phone": phone,
            "country": country,
            "product_model": product,
            "需求": demand
        }
    }
    resp = requests.post(url, headers=headers, json=data)
    if resp.status_code == 201:
        contact_id = resp.json()["id"]
    else:
        # 如果已存在，尝试查找并更新
        search_url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
        search_data = {
            "filterGroups": [{
                "filters": [
                    {"propertyName": "phone", "operator": "EQ", "value": phone}
                ]
            }]
        }
        search_resp = requests.post(search_url, headers=headers, json=search_data)
        results = search_resp.json().get("results", [])
        if results:
            contact_id = results[0]["id"]
            update_url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
            requests.patch(update_url, headers=headers, json=data)
        else:
            return False, "联系人创建失败"
    # 2. 添加备注
    note_url = "https://api.hubapi.com/crm/v3/objects/notes"
    note_data = {
        "properties": {
            "hs_note_body": f"聊天内容：\n{raw_text}\n\n需求：{demand}"
        },
        "associations": [
            {
                "toObjectId": contact_id,
                "toObjectType": "contact"
            }
        ]
    }
    note_resp = requests.post(note_url, headers=headers, json=note_data)
    if note_resp.status_code in [200, 201]:
        return True, "同步成功"
    else:
        return False, "备注同步失败"

# ====== Streamlit主界面 ======
st.title("聊天截图客户信息智能提取工具（百度OCR+HubSpot）")

uploaded_file = st.file_uploader("请上传聊天截图（jpg/png）", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_path = tmp_file.name

    st.image(tmp_path, caption="上传的截图", use_column_width=True)

    with st.spinner("正在识别图片内容..."):
        text_lines = baidu_ocr(tmp_path, BAIDU_API_KEY, BAIDU_SECRET_KEY)
        st.subheader("识别结果：")
        for idx, line in enumerate(text_lines, 1):
            st.markdown(f"{idx}. {line.strip()}")

    # 自动提取信息
    info = extract_info(text_lines)
    st.subheader("自动提取客户信息（可修改）：")
    with st.form("info_form"):
        contact = st.text_input("联系人", info["联系人"])
        phone = st.text_input("电话", info["电话"])
        country = st.text_input("国家", info["国家"])
        product = st.text_input("产品型号", info["产品型号"])
        demand = st.text_area("需求", info["需求"])
        submit = st.form_submit_button("一键同步到HubSpot")
        if submit:
            raw_text = "\n".join(text_lines)
            ok, msg = sync_to_hubspot(contact, phone, country, product, demand, raw_text)
            if ok:
                st.success("已同步到HubSpot！")
            else:
                st.error(f"同步失败：{msg}")

    os.remove(tmp_path)