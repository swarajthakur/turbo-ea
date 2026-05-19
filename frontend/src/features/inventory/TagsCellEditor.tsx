import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import { useTranslation } from "react-i18next";
import type { GridApi } from "ag-grid-community";
import MaterialSymbol from "@/components/MaterialSymbol";
import TagPicker from "@/components/TagPicker";
import type { TagGroup, TagRef } from "@/types";

// AG Grid React v32+ custom editor contract:
// — `props.value` is the initial value
// — `props.onValueChange(newValue)` must be called on every change; AG Grid
//   stores it internally and returns it from `getValue()` when edit ends
// — `props.stopEditing()` ends the edit and commits the latest value
// — `props.api.stopEditing(true)` ends the edit AND discards changes
// useImperativeHandle / forwardRef are NOT consulted for value retrieval.
interface Params {
  value: TagRef[] | undefined;
  groups: TagGroup[];
  typeKey?: string;
  stopEditing?: (suppressNavigateAfterEdit?: boolean) => void;
  onValueChange: (value: TagRef[]) => void;
  api: GridApi;
}

export default function TagsCellEditor(props: Params) {
  const { t } = useTranslation(["common"]);

  const initialIds = useMemo(
    () => (props.value || []).map((tag) => tag.id),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [ids, setIds] = useState<string[]>(initialIds);

  const refsById = useMemo(() => {
    const map = new Map<string, TagRef>();
    for (const g of props.groups) {
      for (const tag of g.tags) {
        map.set(tag.id, {
          id: tag.id,
          name: tag.name,
          color: tag.color,
          group_name: g.name,
        });
      }
    }
    return map;
  }, [props.groups]);

  const handleChange = (nextIds: string[]) => {
    setIds(nextIds);
    const nextTags = nextIds
      .map((id) => refsById.get(id))
      .filter((tag): tag is TagRef => Boolean(tag));
    props.onValueChange(nextTags);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      props.api.stopEditing(true);
    }
  };

  return (
    <Box
      sx={{ p: 1.5, minWidth: 340, bgcolor: "background.paper" }}
      onMouseDown={(e) => e.stopPropagation()}
      onKeyDown={handleKeyDown}
    >
      <TagPicker
        groups={props.groups}
        value={ids}
        onChange={handleChange}
        typeKey={props.typeKey}
        size="small"
        disablePortal
      />
      <Stack direction="row" spacing={1} justifyContent="flex-end" sx={{ mt: 1.5 }}>
        <Button
          size="small"
          onClick={() => props.api.stopEditing(true)}
          startIcon={<MaterialSymbol icon="close" size={16} />}
        >
          {t("common:actions.cancel")}
        </Button>
        <Button
          size="small"
          variant="contained"
          onClick={() => props.stopEditing?.()}
          startIcon={<MaterialSymbol icon="check" size={16} />}
        >
          {t("common:actions.save")}
        </Button>
      </Stack>
    </Box>
  );
}
