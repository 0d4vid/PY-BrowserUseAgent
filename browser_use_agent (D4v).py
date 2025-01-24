from openai import OpenAI
import json
import os
from playwright.async_api import async_playwright
from io import BytesIO
from PIL import Image as PILImage
from pprint import pprint
import asyncio
import base64 

async def main():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    # Initialize OpenAI client
    client = OpenAI(
        base_url="https://api.together.xyz/v1",
        api_key=os.getenv("TOGETHER_API_KEY")  # Set your API key in environment
    )

    tools = [{
    "type": "function",
    "function": {
        "name": "load_page",
        "description": "Go to a webpage.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string"
                }
            },
            "required": [
                "url"
            ],
            "additionalProperties": False
        },
        "strict": True
    }
}, {
    "type": "function",
    "function": {
        "name": "click_element",
        "description": "Click on an element by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {
                    "type": "number"
                }
            },
            "required": [
                "element_id"
            ],
            "additionalProperties": False
        },
        "strict": True
    }
}]

    

    async def get_clickable_elements():
        global clickable_elements

        await page.wait_for_load_state()
        clickable_elements = await page.query_selector_all('a, button, [role="button"], [onclick]')
        labeled_elements = dict()
        
        for index, element in enumerate(clickable_elements):
            text = await element.inner_text()
            cleaned_text = " ".join(text.split())
            if text and await element.is_visible():
                labeled_elements[index] = cleaned_text
        return "The page has loaded and the following element IDs can be clicked" + json.dumps(labeled_elements)

    async def load_page(url):
        await page.goto(url)
        return await get_clickable_elements()

    async def click_element(element_id):
        await clickable_elements[element_id].click()
        return await get_clickable_elements()

    async def get_screenshot():
        screenshot = await page.screenshot()
        img = PILImage.open(BytesIO(screenshot))
        
        # Save locally for debugging
        img.save("screenshot.png")
        
        # Convert to base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    async def send_screenshot_to_llm():
        img_base64 = await get_screenshot()
        return {
            "role": "user",
            "content": [
                {
                    "type": "text", 
                    "text": "Here's the current screen state:"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                }
            ]
        }

    chat_history = [{"role": "user", "content": "Go to Pinterest and find some interesting images"}]

    try:
        while True:
            # Add screenshot to history before each request
            chat_history.append(await send_screenshot_to_llm())
            
            completion = client.chat.completions.create(
                model="meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo",
                messages=chat_history,
                tools=tools
            )

            print("LLM Response:", completion.choices[0].message.content)
            tool_calls = completion.choices[0].message.tool_calls

            if tool_calls:
                chat_history.append(completion.choices[0].message)
                tool_call_name = tool_calls[0].function.name
                
                if tool_call_name == "load_page":
                    url = json.loads(tool_calls[0].function.arguments)["url"]
                    result = await load_page(url)
                    chat_history.append({"role": "function", "name": tool_call_name, "content": result})
                
                elif tool_call_name == "click_element":
                    element_id = json.loads(tool_calls[0].function.arguments)["element_id"]
                    result = await click_element(element_id)
                    chat_history.append({"role": "function", "name": tool_call_name, "content": result})
            else:
                break

    finally:
        await browser.close()
        await p.stop()

        
if __name__ == "__main__":
    asyncio.run(main())