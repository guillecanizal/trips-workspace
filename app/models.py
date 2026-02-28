"""Database models for trips, days, activities, and general items."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    knowledge_general: Mapped[str | None] = mapped_column(Text, nullable=True)

    days: Mapped[list["Day"]] = relationship(
        "Day", back_populates="trip", cascade="all, delete-orphan"
    )
    general_items: Mapped[list["GeneralItem"]] = relationship(
        "GeneralItem", back_populates="trip", cascade="all, delete-orphan"
    )

    def to_dict(self, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "knowledge_general": self.knowledge_general,
        }
        if include_children:
            data["days"] = [day.to_dict(include_children=True) for day in self.days]
            data["general_items"] = [item.to_dict() for item in self.general_items]
        return data


class Day(Base):
    __tablename__ = "days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    hotel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hotel_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hotel_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hotel_reservation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hotel_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    hotel_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    hotel_maps_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    hotel_cancelable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    trip: Mapped[Trip] = relationship("Trip", back_populates="days")
    activities: Mapped[list["Activity"]] = relationship(
        "Activity", back_populates="day", cascade="all, delete-orphan"
    )

    def to_dict(self, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "trip_id": self.trip_id,
            "date": self.date.isoformat() if self.date else None,
            "hotel_name": self.hotel_name,
            "hotel_location": self.hotel_location,
            "hotel_description": self.hotel_description,
            "hotel_reservation_id": self.hotel_reservation_id,
            "hotel_price": self.hotel_price,
            "hotel_link": self.hotel_link,
            "hotel_maps_link": self.hotel_maps_link,
            "hotel_cancelable": self.hotel_cancelable,
            "distance_km": self.distance_km,
            "distance_hours": self.distance_hours,
            "distance_minutes": self.distance_minutes,
        }
        if include_children:
            data["activities"] = [activity.to_dict() for activity in self.activities]
        return data


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("days.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reservation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    maps_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    day: Mapped[Day] = relationship("Day", back_populates="activities")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "day_id": self.day_id,
            "name": self.name,
            "description": self.description,
            "location": self.location,
            "price": self.price,
            "reservation_id": self.reservation_id,
            "link": self.link,
            "maps_link": self.maps_link,
            "cancelable": self.cancelable,
        }


class GeneralItem(Base):
    __tablename__ = "general_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reservation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    maps_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    trip: Mapped[Trip] = relationship("Trip", back_populates="general_items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trip_id": self.trip_id,
            "name": self.name,
            "description": self.description,
            "reservation_id": self.reservation_id,
            "price": self.price,
            "link": self.link,
            "maps_link": self.maps_link,
            "cancelable": self.cancelable,
        }
