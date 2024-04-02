from fastapi import HTTPException
import requests
from dotenv import load_dotenv
import os
from app.schemas.Invitations import InvitationsSchema
from app.repositories import InvitationRepository as invitationRepository
from pymongo.errors import PyMongoError

load_dotenv()

WHATSAPP_API_URL = "https://graph.facebook.com/v18.0/107266568911091/messages"
ACCESS_TOKEN = os.getenv("WHATSAPP_TOKEN")

def sendNetworkInvitationMessage(inviteData: InvitationsSchema):
    data = {
        "messaging_product": "whatsapp",
        "to": inviteData.finalContactInfo,
        "type": "template",
        "template": {
            "name": "unete_eassymo6",
            "language": {
                "code": "es_MX"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": inviteData.censusUser.Entity_Name
                        },
                        {
                            "type": "text",
                            "text": inviteData.userName
                        }
                    ]
                }
            ]
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f'Bearer {ACCESS_TOKEN}'
    }


    try:
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)
        invite_data= {
            "user": inviteData.user,
            "userName": inviteData.userName,
            "inviteStatus": inviteData.inviteStatus.value,
            "censusId": inviteData.censusId,
            "censusUser": inviteData.censusUser.model_dump(),
            "type": inviteData.type.value
        }
        invitationRepository.insert(invite_data)
        return {"message": "ok", "body": response.json()}
    except HTTPException as exeption:
        return {"Error sending whatsapp invite"}
    
def get_user_invites(id: str):
    try:
        invites = list(invitationRepository.find_user_invites(id))
        return {"message": "ok", "body": invites}
    except PyMongoError as e:
        raise HTTPException(status_code=500, detail="Item not found")