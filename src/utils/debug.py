import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=options)

driver.get("https://recordtaskdata.online/")
time.sleep(3)
driver.find_element(By.XPATH, "//input[@placeholder='Username']").send_keys("mahesh30802@gmail.com")
driver.find_element(By.XPATH, "//input[@placeholder='Password']").send_keys("9606768755")
driver.find_element(By.XPATH, "//button[contains(text(),'Sign In')]").click()
time.sleep(3)

driver.get("https://recordtaskdata.online/start-task")
time.sleep(3)

sel = Select(driver.find_element(By.TAG_NAME, "select"))
sel.select_by_visible_text("QRCode - 1")
time.sleep(3)

# Dump form HTML for debugging field IDs
forms = driver.find_elements(By.TAG_NAME, "form")
print(f"Forms found: {len(forms)}")
for i, f in enumerate(forms):
    print(f"\n--- Form {i} innerHTML (first 3000 chars) ---")
    print(f.get_attribute('innerHTML')[:3000])

# Check if pre-filled data exists on the page
src = driver.page_source
print("\n=== Checking for pre-filled data ===")
for keyword in ["Pachter", "Corelogic", "Steve"]:
    print(f"{keyword} in source:", keyword in src)
    idx = src.find(keyword)
    if idx > 0:
        print(f"Context: ...{src[idx-200:idx+200]}...")

# Dump all input field values
print("\n=== Input field values ===")
for field_id in ["name", "designation", "company_name", "website", "address", "email", "office_contact"]:
    try:
        el = driver.find_element(By.ID, field_id)
        print(f"  {field_id}: '{el.get_attribute('value')}'")
    except Exception:
        print(f"  {field_id}: NOT FOUND")

driver.quit()
