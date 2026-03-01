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
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET,PUT,DELETE'
    }

    # --- API Gateway Compatibility ---
    http_method = event.get('httpMethod')
    if not http_method:
        try:
            http_method = event['requestContext']['http']['method']
        except KeyError:
            http_method = 'OPTIONS'

    # --- Preflight Check (OPTIONS) ---
    if http_method == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': ''}

    try:
        # ==========================================
        # CREATE: Submit a New Ticket (POST)
        # ==========================================
        if http_method == 'POST':
            body = json.loads(event['body'])
            ticket_id = str(uuid.uuid4())
            image_key = None
            
            if 'imageBase64' in body and body['imageBase64']:
                image_data = body['imageBase64']
                if "," in image_data:
                    image_data = image_data.split(",")[1]
                
                decoded_image = base64.b64decode(image_data)
                image_key = f"{ticket_id}.jpg"
                
                s3.put_object(Bucket=BUCKET_NAME, Key=image_key, Body=decoded_image, ContentType='image/jpeg')

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
            
            if image_key:
                item['imageKey'] = image_key

            table.put_item(Item=item)
            return {'statusCode': 201, 'headers': headers, 'body': json.dumps({'message': 'Ticket created', 'ticketId': ticket_id})}

        # ==========================================
        # READ: Get All Tickets (GET)
        # ==========================================
        elif http_method == 'GET':
            response = table.scan()
            items = response.get('Items', [])
            
            for item in items:
                if 'imageKey' in item:
                    item['imageUrl'] = s3.generate_presigned_url('get_object', Params={'Bucket': BUCKET_NAME, 'Key': item['imageKey']}, ExpiresIn=3600)
            
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
            
            existing_item = table.get_item(Key={'ticketId': ticket_id}).get('Item', {})

            # --- SNS Email Trigger ---
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
            
            existing_item = table.get_item(Key={'ticketId': ticket_id}).get('Item', {})
            if 'imageKey' in existing_item:
                try:
                    s3.delete_object(Bucket=BUCKET_NAME, Key=existing_item['imageKey'])
                except Exception:
                    pass 
            
            table.delete_item(Key={'ticketId': ticket_id})
            return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'message': 'Deleted'})}

        return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'message': 'Unsupported method'})}
        
    except Exception as e:
        return {'statusCode': 500, 'headers': headers, 'body': json.dumps({'error': str(e)})}
