from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from utils.security import get_current_user
from services.database import get_database, DatabaseService

router = APIRouter()

# Models
class ScheduleEventBase(BaseModel):
    title: str
    description: Optional[str] = None
    date: str
    start_time: str
    end_time: str
    type: str
    class_id: Optional[str] = None
    is_all_day: Optional[bool] = False

class ScheduleEventCreate(ScheduleEventBase):
    repeat_weekly: Optional[bool] = False

class ScheduleEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    type: Optional[str] = None
    class_id: Optional[str] = None
    is_all_day: Optional[bool] = None

class ScheduleEventResponse(ScheduleEventBase):
    id: str
    teacher_id: str
    class_name: Optional[str] = None
    created_at: str
    updated_at: str

@router.get("/", response_model=List[dict])
async def list_schedule_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Get all schedule events for the current teacher"""
    events = await db.get_schedule_events(
        teacher_id=current_user["id"],
        start_date=start_date,
        end_date=end_date
    )
    
    # Format dates correctly as strings if they come out as datetime
    for event in events:
        if event.get("created_at"):
            event["created_at"] = event["created_at"].isoformat() if hasattr(event["created_at"], 'isoformat') else str(event["created_at"])
        if event.get("updated_at"):
            event["updated_at"] = event["updated_at"].isoformat() if hasattr(event["updated_at"], 'isoformat') else str(event["updated_at"])
            
    return events

@router.post("/", response_model=dict)
async def create_schedule_event(
    event: ScheduleEventCreate,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Create a new schedule event"""
    event_data = event.model_dump(exclude_unset=True)
    repeat_weekly = event_data.pop("repeat_weekly", False)
    event_data["teacher_id"] = current_user["id"]
    
    created_event = await db.create_schedule_event(event_data)
    if not created_event:
        raise HTTPException(status_code=500, detail="Failed to create event")
        
    if repeat_weekly:
        try:
            base_date = datetime.strptime(event_data["date"], "%Y-%m-%d")
            for i in range(1, 16): # Schedule for the next 15 weeks
                next_date = base_date + timedelta(days=7 * i)
                recurring_event_data = event_data.copy()
                recurring_event_data["date"] = next_date.strftime("%Y-%m-%d")
                await db.create_schedule_event(recurring_event_data)
        except Exception as e:
            # If recurring fails, we still return the first created event
            pass
        
    if created_event.get("created_at"):
        created_event["created_at"] = created_event["created_at"].isoformat() if hasattr(created_event["created_at"], 'isoformat') else str(created_event["created_at"])
    if created_event.get("updated_at"):
        created_event["updated_at"] = created_event["updated_at"].isoformat() if hasattr(created_event["updated_at"], 'isoformat') else str(created_event["updated_at"])

    # Fire notification
    try:
        from services.notification_service import notify
        repeat_note = " (repeating weekly)" if event.repeat_weekly else ""
        await notify(
            teacher_id=current_user["id"],
            title="Calendar event added",
            message=f'"{event.title}" scheduled for {event.date} at {event.start_time}{repeat_note}.',
            notification_type="calendar_event",
            metadata={"event_id": str(created_event.get("id", "")), "date": event.date, "type": event.type},
        )
    except Exception:
        pass

    return created_event

@router.put("/{event_id}", response_model=dict)
async def update_schedule_event(
    event_id: str,
    event: ScheduleEventUpdate,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Update a schedule event"""
    # Check ownership
    existing_event = await db.get_schedule_event(event_id, current_user["id"])
    if not existing_event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    update_data = event.model_dump(exclude_unset=True)
    if not update_data:
        return existing_event
        
    updated_event = await db.update_schedule_event(event_id, current_user["id"], update_data)
    if not updated_event:
        raise HTTPException(status_code=500, detail="Failed to update event")
        
    if updated_event.get("created_at"):
        updated_event["created_at"] = updated_event["created_at"].isoformat() if hasattr(updated_event["created_at"], 'isoformat') else str(updated_event["created_at"])
    if updated_event.get("updated_at"):
        updated_event["updated_at"] = updated_event["updated_at"].isoformat() if hasattr(updated_event["updated_at"], 'isoformat') else str(updated_event["updated_at"])
        
    return updated_event

@router.delete("/{event_id}")
async def delete_schedule_event(
    event_id: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database)
):
    """Delete a schedule event"""
    success = await db.delete_schedule_event(event_id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Event not found or failed to delete")
        
    return {"status": "success", "message": "Event deleted successfully"}
