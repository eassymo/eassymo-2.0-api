from pydantic import BaseModel, Field
from typing import Any, List


class FilterItem(BaseModel):
    id: str
    description: str
    value: Any

    def toJson(self):
        data = self.model_dump()
        data["value"] = str(self.value)

        return data


class FilterSection(BaseModel):
    id: str = Field(description="Filter section id")
    filterSectionTitle: str = Field(None)
    filters: List[FilterItem]

    def toJson(self):
        data = self.model_dump()
        filter_items = []

        for filter_item in self.filters:
            filter_items.append(filter_item.toJson())

        data["filters"] = filter_items

        return data
