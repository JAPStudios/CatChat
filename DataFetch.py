import requests
def import_facebook_messages(access_token):
    url = "https://graph.facebook.com/v12.0/me/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        messages = response.json()["data"]
        for message in messages:
            print(f"Imported message: {message}")
    else:
        print(f"Failed to import messages from Facebook: {response.status_code}")
facebook_access_token = "YOUR_FACEBOOK_ACCESS_TOKEN"
import_facebook_messages(facebook_access_token)