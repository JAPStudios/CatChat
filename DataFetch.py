import requests
def import_facebook_messages(access_token):
    url = "https://graph.facebook.com/v13.0/me/messages"
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
import tweepy
consumer_key = 'YOUR_CONSUMER_KEY'
consumer_secret = 'YOUR_CONSUMER_SECRET'
access_token = 'YOUR_ACCESS_TOKEN'
access_token_secret = 'YOUR_ACCESS_TOKEN_SECRET'
auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
auth.set_access_token(access_token, access_token_secret)
api = tweepy.API(auth)
def fetch_twitter_messages():
    messages = []
    for message in api.list_direct_messages():
        messages.append({
            'sender_id': message.message_create['sender_id'],
            'recipient_id': message.message_create['target']['recipient_id'],
            'text': message.message_create['message_data']['text'],
            'timestamp': message.created_timestamp
        })
    return messages
twitter_messages = fetch_twitter_messages()
print(twitter_messages)