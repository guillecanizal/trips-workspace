"""Pydantic schemas for MCP tool inputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HotelInput(BaseModel):
    name: str = Field(description="Hotel name")
    price: float | None = Field(default=None, description="Price per night in euros")
    location: str | None = Field(default=None, description="Hotel location or neighborhood")
    description: str | None = Field(default=None, description="Short description")
    reservation_id: str | None = Field(default=None, description="Booking reference")
    link: str | None = Field(default=None, description="Booking URL")
    cancelable: bool | None = Field(default=None, description="Whether booking is cancelable")


class ActivityInput(BaseModel):
    name: str = Field(description="Activity name")
    price: float | None = Field(default=None, description="Cost in euros")
    location: str | None = Field(default=None, description="Location or address")
    description: str | None = Field(default=None, description="Short description")
    reservation_id: str | None = Field(default=None, description="Booking reference")
    link: str | None = Field(default=None, description="Website or booking URL")
    cancelable: bool | None = Field(default=None, description="Whether booking is cancelable")


class PlanDayInput(BaseModel):
    trip_id: int = Field(description="Trip ID returned by create_trip or list_trips")
    day_number: int = Field(description="Day number (1-based, e.g. 1 = first day of trip)")
    hotel: HotelInput | None = Field(default=None, description="Hotel for this night. Omit if no overnight stay (last day) or same hotel as previous day.")
    activities: list[ActivityInput] = Field(default_factory=list, description="Activities for this day, in chronological order")


class CreateTripInput(BaseModel):
    name: str = Field(description="Trip name, e.g. 'Kyoto 2026'")
    destination: str = Field(description="Main destination, e.g. 'Kyoto, Japan'")
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")
    description: str | None = Field(default=None, description="Optional trip notes")


class UpdateTripInput(BaseModel):
    trip_id: int = Field(description="Trip ID to update")
    name: str | None = Field(default=None, description="New trip name")
    description: str | None = Field(default=None, description="New description")
    start_date: str | None = Field(default=None, description="New start date YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="New end date YYYY-MM-DD")
