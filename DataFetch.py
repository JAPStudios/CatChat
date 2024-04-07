import requests
def fetch_messages_from_platform(access_token):
    url = "https://api.example.com/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for non-2xx status codes
        
        messages = response.json()
        return messages
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching messages: {e}")
        return None
platform_access_token = "your_platform_access_token_here"
messages = fetch_messages_from_platform(platform_access_token)
if messages:
    for message in messages:
        print(message)  
import discord
import tweepy
import requests
class Discord:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.client = discord.Client()
    async def fetch_messages(self, channel_id):
        await self.client.start(self.bot_token)
        channel = self.client.get_channel(channel_id)
        messages = await channel.history(limit=None).flatten()
        await self.client.close()
        return messages
class FacebookMessenger:
    def __init__(self, access_token):
        self.access_token = access_token
    def fetch_messages(self, user_id):
        url = f"https://graph.facebook.com/{user_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()['data']
        else:
            return None
class Twitter:
    def __init__(self, consumer_key, consumer_secret, access_token, access_token_secret):
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(access_token, access_token_secret)
        self.api = tweepy.API(auth)
    def fetch_messages(self):
        messages = []
        for message in self.api.list_direct_messages():
            messages.append({
                'sender_id': message.message_create['sender_id'],
                'recipient_id': message.message_create['target']['recipient_id'],
                'text': message.message_create['message_data']['text'],
                'timestamp': message.created_timestamp
            })
        return messages
def import_messages():
    discord_token = 'YOUR_DISCORD_BOT_TOKEN'
    discord_client = DiscordClient(discord_token)
    discord_channel_id = 'CHANNEL_ID_TO_FETCH_MESSAGES_FROM'
    discord_messages = discord_client.fetch_messages(discord_channel_id)
    if discord_messages:
        print("Imported messages from Discord.")
    facebook_access_token = "YOUR_FACEBOOK_ACCESS_TOKEN"
    fb_messenger = FacebookMessenger(facebook_access_token)
    fb_user_id = 'USER_ID_TO_FETCH_CHAT_DATA_FROM'
    facebook_messages = fb_messenger.fetch_messages(fb_user_id)
    if facebook_messages:
        print("Imported messages from Facebook.")
    twitter_consumer_key = 'YOUR_TWITTER_CONSUMER_KEY'
    twitter_consumer_secret = 'YOUR_TWITTER_CONSUMER_SECRET'
    twitter_access_token = 'YOUR_TWITTER_ACCESS_TOKEN'
    twitter_access_token_secret = 'YOUR_TWITTER_ACCESS_TOKEN_SECRET'
    twitter_client = TwitterDMs(twitter_consumer_key, twitter_consumer_secret,
                                twitter_access_token, twitter_access_token_secret)
    twitter_messages = twitter_client.fetch_messages()
    if twitter_messages:
        print("Imported messages from Twitter.")
if __name__ == "__main__":
    import_messages()