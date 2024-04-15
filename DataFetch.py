import requests
def import_data_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.text
            print("Data imported successfully:")
            print(data)
            return data
        else:
            print(f"Error: Failed to fetch data from URL ({response.status_code})")
    except requests.RequestException as e:
        print(f"An error occurred during the request: {str(e)}")
url = 'https://facebook.com'
imported_data = import_data_from_url(url)