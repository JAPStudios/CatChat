from flask import Flask, request, jsonify
import requests
        $(document).ready(function() {
            $('.platform-icon').click(function() {
                var url = $(this).data('url');
                retrieveData(url);
            });
        }
        function retrieveData(url) {
            $.ajax({
                url: '/retrieve_data',
                method: 'POST',
                data: { url: url },
                success: function(response) {
                    console.log("Data retrieved successfully:", response);
                },
                error: function(xhr, status, error) {
                    console.error("Failed to retrieve data:", error);
                }
            });
        }
    </script>
</body>
</html>
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
return f"Error: Failed to fetch data from URL ({response.status_code})"
    except requests.RequestException as e:
        return f"An error occurred during the request: {str(e)}"
@app.route('/retrieve_data', methods=['POST'])
def retrieve_data():
    url = request.form['url']
    imported_data = import_data_from_url(url)
    return jsonify({'data': imported_data})
if __name__ == '__main__':
    app.run(debug=True)