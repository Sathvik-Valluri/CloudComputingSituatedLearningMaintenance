# CloudComputingSituatedLearningMaintenance - College Assignment
Large Manufacturing Plants face frequent equipment breakdowns. Maintenance teams handle requests manually causing delays. 
This system aims to digitize maintenance request handling

# Serverless Smart Maintenance Request Management System (SMRMS) - Airbus College Assignment

## 1. Initial Problem Statement
Large manufacturing plants and aviation maintenance facilities face frequent equipment breakdowns. Currently, maintenance teams handle requests manually using paper forms or unencrypted emails. This results in:
* **High Latency:** Technicians spend hours locating requests, leading to preventable downtime.
* **Data Black Holes:** No central database exists to track failure trends or enable predictive maintenance.
* **Scaling Issues:** During turnaround periods, the manual system collapses.

## 2. Gap / Challenge Identified
The core challenge was to modernize this workflow by designing a **Serverless, highly available, and secure system** that allows operators to submit requests via a mobile-friendly interface, automatically route them, and securely store media evidence (images) without creating database bottlenecks.

## 3. Approach & Architecture Design
The solution is a 100% serverless architecture built on AWS to ensure zero idle costs and infinite scalability. 

**Architectural Components:**
* **Frontend:** Hosted on GitHub Pages (HTML/CSS/JS).
* **API Layer:** Amazon API Gateway handles routing and CORS preflight checks.
* **Compute:** AWS Lambda (Python 3.12) executes all business logic.
* **Database:** Amazon DynamoDB (NoSQL) stores ticket metadata and state.
* **Object Storage:** Amazon S3 securely stores incident photos, providing temporary Pre-Signed URLs to the frontend.
* **Notifications:** Amazon SNS triggers real-time email alerts to operators upon ticket completion.

**Key Design Decisions:**
1. **Cost Optimization:** By dropping heavy frameworks and utilizing AWS Free Tier services exclusively, the operational cost is $0.
2. **Storage Efficiency:** To bypass DynamoDB's 400KB item limit, images are routed to S3, and only the S3 Object Key is stored in the database. Furthermore, Lambda is programmed to automatically delete images from S3 when a ticket is marked "Complete," drastically reducing storage bloat.

## 4. Implementation Steps
1. **DynamoDB:** Created table `MaintenanceRequests` with Partition Key `ticketId`.
2. **S3:** Created a private bucket for images. Block Public Access remains ON to ensure security; images are served via Lambda-generated Pre-Signed URLs.
3. **SNS:** Created a Standard Topic (`MaintenanceAlerts`) with an Email subscription for completion notifications.
4. **Lambda:** Deployed Python code utilizing the `boto3` SDK. Attached IAM policies for `DynamoDBFullAccess`, `S3FullAccess`, and `SNSFullAccess`.
5. **API Gateway:** Created an HTTP API, configured CORS (allowing all origins/methods for testing), and attached it as a trigger to the Lambda function.
6. **Frontend:** Deployed `index.html` to GitHub Pages, pointing `API_URL` to the API Gateway endpoint.

## 5. Test Setup / Environment
* **Local Testing:** Python simple HTTP server (`python -m http.server 8000`) used to bypass local `file:///` CORS restrictions during development.
* **Cloud Environment:** AWS `us-east-1` region.
* **Browser:** Tested successfully on modern Chromium-based browsers.

## 6. Testing & Performance Measurement
* **CRUD Verification:** Successfully tested Create (Operator POST), Read (Technician GET), Update (Technician PUT + SNS Trigger), and Delete (Technician DELETE + S3 Cleanup).
* **Latency:** AWS CloudWatch metrics indicate Lambda cold starts average ~800ms, while warm invocations execute in **< 250ms**, providing a near-instantaneous experience for the end user.

## 7. Challenges & Resolutions (Lessons Learned)
During the development and integration phases, several cloud-specific challenges were identified and resolved:
1. **IAM Permission Denials:** Lambda initially failed to write to DynamoDB. *Resolution:* Traced the `AccessDeniedException` and attached explicit IAM execution roles for DynamoDB, S3, and SNS.
2. **CORS and Preflight (OPTIONS) Failures:** Browsers blocked the connection from the local testing environment to API Gateway. *Resolution:* Configured API Gateway to accept `*` origins and updated the Lambda Python script to explicitly return a `200 OK` status for preflight `OPTIONS` requests.
3. **SNS Protocol Limitations:** Initially created a FIFO (First-In-First-Out) SNS topic, which does not support Email protocols. *Resolution:* Re-architected the topic to a "Standard" SNS topic to allow direct-to-email technician alerts.
4. **API Gateway 10MB Payload Limit:** Uploading high-resolution smartphone images (which bloat by 33% when Base64 encoded) caused catastrophic API Gateway connection timeouts and 502 errors. *Resolution:* Shifted the compute load to the client-side. Implemented an HTML5 Canvas Javascript function in the frontend to automatically compress and resize images to <500KB *before* transmission to AWS, bypassing the limit and dramatically improving upload speeds.

## 8. Future Work
* **Authentication:** Implement Amazon Cognito User Pools to enforce strict Operator vs. Technician access controls.
* **Predictive Analytics:** Export DynamoDB data to AWS Glue and Athena to identify equipment with the highest failure rates.
* **Automated Dispatch:** Integrate AWS Step Functions to automatically page the nearest available technician based on aircraft program.
