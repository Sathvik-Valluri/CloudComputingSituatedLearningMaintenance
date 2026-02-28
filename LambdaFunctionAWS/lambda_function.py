import json
import boto3
import uuid
import base64
from datetime import datetime

# ==========================================
# 1. AWS RESOURCE INITIALIZATION
# ==========================================
# We initialize these outside the handler function so AWS can "cache" them.
# This makes subsequent Lambda runs much faster (called a "Warm Start").
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('MaintenanceRequests')
s3 = boto3.client('s3')
sns = boto3.client('sns')

# --- MY AWS CONFIGURATION ---
BUCKET_NAME = 'smrms-images-cloud-2026' 
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:304361287272:MaintenanceAlertsStandard'

# ==========================================
# 2. MAIN FUNCTION HANDLER
# ==========================================
def lambda_handler(event, context):
    
    # --- CORS Headers ---
    # These headers tell the web browser "Yes, it is safe to accept data from this server."
    # Without these, the browser's security rules will block the connection.
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET,PUT,DELETE'
    }

    # --- API Gateway Compatibility ---
    # AWS has two types of API Gateways (REST vs HTTP). They format data slightly differently.
    # This block safely extracts the HTTP Method (GET, POST, etc.) regardless of which API type is used.
    http_method = event.get('httpMethod')
    if not http_method:
        try:
            http_method = event['requestContext']['http']['method']
        except KeyError:
            http_method = 'OPTIONS'

    # --- Preflight Check (OPTIONS) ---
    # Browsers send a blank "OPTIONS" request first to check if they are allowed to talk to the server.
    # We immediately reply "200 OK" to let the browser know it can proceed.
    if http_method == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': ''}

    try:
        # ==========================================
        # CREATE: Submit a New Ticket (POST)
        # ==========================================
        if http_method == 'POST':
            # Convert the incoming JSON string from the frontend into a Python dictionary
            body = json.loads(event['body'])
            
            # Generate a unique, random ID for the ticket
            ticket_id = str(uuid.uuid4())
            image_key = None
            
            # --- Image Processing ---
            # Images are sent from the HTML as a massive string of text (Base64).
            # We strip out the HTML formatting, decode the text back into a binary image,
            # and upload it to our secure S3 Bucket.
            if 'imageBase64' in body and body['imageBase64']:
                image_data = body['imageBase64']
                if "," in image_data:
                    image_data = image_data.split(",")[1]
                
                decoded_image = base64.b64decode(image_data)
                image_key = f"{ticket_id}.jpg"
                
                s3.put_object(Bucket=BUCKET_NAME, Key=image_key, Body=decoded_image, ContentType='image/jpeg')

            # --- Database Entry ---
            # Construct the data package to save into DynamoDB
            item = {
                'ticketId': ticket_id,
                'aircraftProgram': body.get('aircraftProgram', 'Unknown'),
                'equipmentType': body.get('equipmentType', 'Unknown'),
                'equipmentId': body.get('equipmentId', 'Unknown'),
                'description': body.get('description', ''),
                'priority': body.get('priority', 'Low'),
                'status': 'Pending',
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Only add the imageKey to the database if the user actually uploaded an image
            if image_key:
                item['imageKey'] = image_key

            # Save to DynamoDB
            table.put_item(Item=item)
            return {'statusCode': 201, 'headers': headers, 'body': json.dumps({'message': 'Ticket created', 'ticketId': ticket_id})}

        # ==========================================
        # READ: Get All Tickets (GET)
        # ==========================================
        elif http_method == 'GET':
            # Pull every single ticket from the DynamoDB table
            response = table.scan()
            items = response.get('Items', [])
            
            # --- Secure Image Links ---
            # S3 is private by default. We generate a temporary "Pre-signed URL" for each image.
            # This allows the frontend to display the image securely, but the link expires in 1 hour.
            for item in items:
                if 'imageKey' in item:
                    item['imageUrl'] = s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET_NAME, 'Key': item['imageKey']}, ExpiresIn=3600)
            
            # Sort the tickets so the newest ones appear at the top
            items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return {'statusCode': 200, 'headers': headers, 'body': json.dumps(items)}

        # ==========================================
        # UPDATE: Change Status & Send Email (PUT)
        # ==========================================
        elif http_method == 'PUT':
            body = json.loads(event['body'])
            ticket_id = body['ticketId']
            new_status = body['status']
            send_email = body.get('sendEmail', False)
            
            # Fetch the existing ticket to see if it has an image attached
            existing_item = table.get_item(Key={'ticketId': ticket_id}).get('Item', {})

            # --- Space Saving Logic ---
            # If the ticket is marked 'Complete', we delete the heavy image from S3 to save storage costs.
            if new_status == 'Complete' and 'imageKey' in existing_item:
                try:
                    s3.delete_object(Bucket=BUCKET_NAME, Key=existing_item['imageKey'])
                except Exception as e:
                    print(f"S3 Delete Error: {e}")
            
            # --- SNS Email Trigger ---
            # If the technician checked the "Notify Operator" box AND marked it Complete, send an email.
            if send_email and new_status == 'Complete':
                eq_id = existing_item.get('equipmentId', 'Unknown Equipment')
                program = existing_item.get('aircraftProgram', '')
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject=f"RESOLVED: {program} - {eq_id}",
                    Message=f"Good news!\n\nThe maintenance request for {eq_id} ({program}) has been marked as COMPLETE by the technician.\n\nTicket ID: {ticket_id}"
                )

            # Update the status text in the database
            table.update_item(
                Key={'ticketId': ticket_id},
                UpdateExpression="set #s = :stat",
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':stat': new_status}
            )
            return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'message': 'Status updated'})}

        # ==========================================
        # DELETE: Remove Ticket Entirely (DELETE)
        # ==========================================
        elif http_method == 'DELETE':
            body = json.loads(event['body'])
            ticket_id = body['ticketId']
            
            # Always check for and delete the S3 image first so we don't leave orphaned files in our bucket
            existing_item = table.get_item(Key={'ticketId': ticket_id}).get('Item', {})
            if 'imageKey' in existing_item:
                try:
                    s3.delete_object(Bucket=BUCKET_NAME, Key=existing_item['imageKey'])
                except Exception:
                    pass # Fail silently if the image is already gone
            
            # Delete the database row
            table.delete_item(Key={'ticketId': ticket_id})
            return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'message': 'Deleted'})}

        # Fallback if the frontend sends an unsupported method like PATCH
        return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'message': 'Unsupported method'})}
        
    # Catch any unexpected Python crashes and send a clean 500 Server Error back to the browser
    except Exception as e:
        return {'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': str(e)})}
