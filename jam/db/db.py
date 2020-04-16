import json
import datetime

from werkzeug._compat import iteritems, text_type, integer_types, string_types, to_bytes, to_unicode

from ..common import consts, error_message, json_defaul_handler

class AbstractDB(object):
    def __init__(self):
        self.db_type = None
        self.db_info = None
        self.DDL_ROLLBACK = False
        self.NEED_GENERATOR = False
        self.CAN_CHANGE_NOT_NULL = True
        self.FROM = '"%s" AS %s'
        self.LEFT_OUTER_JOIN = 'LEFT OUTER JOIN "%s" AS %s'
        self.FIELD_AS = 'AS'
        self.DESC_NULLS = None
        self.ASC_NULLS = None

    @property
    def params(self):
        return {
            'name': None,
            'dns': False,
            'lib': [],
            'server': False,
            'database': True,
            'login': False,
            'password': False,
            'encoding': False,
            'host': False,
            'port': False,
            'ddl_rollback': self.DDL_ROLLBACK,
            'generator': self.NEED_GENERATOR,
            'can_change_not_null': self.CAN_CHANGE_NOT_NULL,
            'import_support': True
        }
    @property
    def arg_params(self):
        return False

    def connect(self, db_info):
        pass

    def value_literal(self, index):
        return '?'

    def identifier_case(self, name):
        return name.upper()

    def get_select(self, query, fields_clause, from_clause, where_clause, group_clause, order_clause, fields):
        pass

    def cast_date(self, date_str):
        return "CAST('" + date_str + "' AS DATE)"

    def cast_datetime(self, datetime_str):
        return "CAST('" + datetime_str + "' AS TIMESTAMP)"

    def convert_like(self, field_name, val, data_type):
        return 'UPPER(%s)' % field_name, val.upper()

    def create_table(self, table_name, fields, gen_name=None, foreign_fields=None):
        pass

    def drop_table(self, table_name, gen_name):
        pass

    def create_index(self, index_name, table_name, unique, fields, desc):
        pass

    def drop_index(self, table_name, index_name):
        pass

    def next_sequence(self, table_name):
        pass

    def before_restart_sequence(self, gen_name):
        pass

    def restart_sequence(self, table_name, value):
        pass

    def process_query_params(self, params, cursor):
        result = []
        for p in params:
            if type(p) == tuple:
                value, data_type = p
            else:
                value = p
            result.append(value)
        return result

    def process_query_result(self, rows):
        return [list(row) for row in rows]

    def default_value(self, field_info):
        result = field_info.default_value
        if not result is None:
            if field_info.data_type == consts.TEXT:
                result =  "'%s'" % result
            elif field_info.data_type == consts.BOOLEAN:
                if result == 'true':
                    result = '1'
                elif result == 'false':
                    result = '0'
                else:
                    result = ''
            elif field_info.data_type == consts.DATE:
                result = "'%s'" % datetime.date.today().strftime('%Y-%m-%d')
            elif field_info.data_type == consts.DATETIME:
                result = "'%s'" % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        elif field_info.data_type in [consts.TEXT, consts.IMAGE, consts.FILE]:
            return "''"
        return result

    def before_insert(self, cursor, pk_field):
        pass

    def after_insert(self, cursor, pk_field):
        pass

    def returning(self, pk_field):
        return ''

    def insert_query(self, pk_field):
        return 'INSERT INTO "%s" (%s) VALUES (%s)'

    def insert_record(self, delta, cursor, changes, details_changes):
        if delta._deleted_flag_field:
            delta._deleted_flag_field.data = 0
        pk = delta._primary_key_field
        self.before_insert(cursor, pk)
        row = []
        fields = []
        values = []
        index = 0
        for field in delta.fields:
            if not (field == pk and not pk.data):
                index += 1
                fields.append('"%s"' % field.db_field_name)
                values.append('%s' % self.value_literal(index))
                if field.data is None and not field.default_value is None:
                    field.data = field.get_default_value()
                value = (field.data, field.data_type)
                row.append(value)
        if len(delta.fields) != len(delta._fields):
            dif_fields = list(set(delta._fields).difference(delta.fields))
            for field in dif_fields:
                if not field.default_value is None:
                    index += 1
                    fields.append('"%s"' % field.db_field_name)
                    values.append('%s' % self.value_literal(index))
                    value = (field.get_default_value(), field.data_type)
                    row.append(value)
        fields = ', '.join(fields)
        values = ', '.join(values)
        sql = self.insert_query(pk) % (delta.table_name, fields, values)
        row = self.process_query_params(row, cursor)
        delta.execute_query(cursor, sql, row, arg_params=self.arg_params)
        if pk:
            self.after_insert(cursor, pk)
        changes.append([delta.get_rec_info()[consts.REC_LOG_REC], delta._dataset[delta.rec_no], details_changes])

    def update_record(self, delta, cursor, changes, details_changes):
        row = []
        fields = []
        index = 0
        pk = delta._primary_key_field
        command = 'UPDATE "%s" SET ' % delta.table_name
        for field in delta.fields:
            valid = field.field_name != delta._record_version and field != pk
            if delta.lock_active and field.data == field.old_data:
                valid = False
            if valid:
                index += 1
                fields.append('"%s"=%s' % (field.db_field_name, self.value_literal(index)))
                value = (field.data, field.data_type)
                if field.field_name == delta._deleted_flag:
                    value = (0, field.data_type)
                row.append(value)
        fields = ', '.join(fields)
        if delta.lock_active:
            fields = ' %s, "%s"=COALESCE("%s", 0)+1' % \
            (fields, delta._record_version_db_field_name, delta._record_version_db_field_name)
        if delta._primary_key_field.data_type == consts.TEXT:
            id_literal = "'%s'" % delta._primary_key_field.value
        else:
            id_literal = "%s" % delta._primary_key_field.value
        where = ' WHERE "%s" = %s' % (delta._primary_key_db_field_name, id_literal)
        sql = ''.join([command, fields, where])
        row = self.process_query_params(row, cursor)
        delta.execute_query(cursor, sql, row, arg_params=self.arg_params)
        if delta.lock_active:
            delta.execute_query(cursor, 'SELECT "%s" FROM "%s" WHERE "%s"=%s' % \
                (delta._record_version_db_field_name, delta.table_name, \
                delta._primary_key_db_field_name, pk.data))
            r = cursor.fetchone()
            record_version = r[0]
            if record_version != delta._record_version_field.value + 1:
                raise Exception(consts.language('edit_record_modified'))
            delta._record_version_field.data = record_version
        changes.append([delta.get_rec_info()[consts.REC_LOG_REC], delta._dataset[delta.rec_no], details_changes])

    def delete_record(self, delta, cursor, changes, details_changes):
        log_rec = delta.get_rec_info()[consts.REC_LOG_REC]
        soft_delete = delta.soft_delete
        if delta.master:
            soft_delete = delta.master.soft_delete
        if delta._primary_key_field.data_type == consts.TEXT:
            id_literal = "'%s'" % delta._primary_key_field.value
        else:
            id_literal = "%s" % delta._primary_key_field.value
        if soft_delete:
            sql = 'UPDATE "%s" SET "%s" = 1 WHERE "%s" = %s' % \
                (delta.table_name, delta._deleted_flag_db_field_name,
                delta._primary_key_db_field_name, id_literal)
        else:
            sql = 'DELETE FROM "%s" WHERE "%s" = %s' % \
                (delta.table_name, delta._primary_key_db_field_name, id_literal)
        delta.execute_query(cursor, sql)
        changes.append([log_rec, None, None])

    def get_user(self, delta):
        user = None
        if delta.session:
            try:
                user = delta.session.get('user_info')['user_name']
            except:
                pass
        return user

    def save_history(self, delta, connection, cursor):
        if delta.task.history_item and delta.keep_history and delta.record_status != consts.RECORD_DETAILS_MODIFIED:
            changes = None
            user = self.get_user(delta)
            item_id = delta.ID
            if delta.master:
                item_id = delta.prototype.ID
            if delta.record_status != consts.RECORD_DELETED:
                old_rec = delta.get_rec_info()[consts.REC_OLD_REC]
                new_rec = delta._dataset[delta.rec_no]
                f_list = []
                for f in delta.fields:
                    if not f.system_field():
                        new = new_rec[f.bind_index]
                        old = None
                        if old_rec:
                            old = old_rec[f.bind_index]
                        if old != new:
                            f_list.append([f.ID, new])
                changes_str = json.dumps(f_list, separators=(',',':'), default=json_defaul_handler)
                changes = ('%s%s' % ('0', changes_str), consts.LONGTEXT)
            params = [item_id, delta._primary_key_field.value, delta.record_status, changes, user, datetime.datetime.now()]
            params = self.process_query_params(params, cursor)
            delta.execute_query(cursor, delta.task.history_sql, params, arg_params=self.arg_params)

    def update_deleted_detail(self, delta, detail, cursor):
        fields = [detail._primary_key]
        detail.open(fields=fields, open_empty=True)
        sql = 'SELECT "%s" FROM "%s" WHERE "%s" = %s AND "%s" = %s and "%s" = 0' % \
            (detail._primary_key_db_field_name, detail.table_name,
            detail._master_id_db_field_name, delta.ID,
            detail._master_rec_id_db_field_name, delta._primary_key_field.value,
            detail._deleted_flag_db_field_name)
        try:
            cursor.execute(sql)
            rows = self.process_query_result(cursor.fetchall())
        except Exception as x:
            delta.log.exception(error_message(x))
            raise Exception(x)
        detail._dataset = rows

    def delete_detail_records(self, delta, connection, cursor, detail):
        if delta._primary_key_field.data_type == consts.TEXT:
            id_literal = "'%s'" % delta._primary_key_field.value
        else:
            id_literal = "%s" % delta._primary_key_field.value
        if detail._master_id:
            if delta.soft_delete:
                sql = 'UPDATE "%s" SET "%s" = 1 WHERE "%s" = %s AND "%s" = %s' % \
                    (detail.table_name, detail._deleted_flag_db_field_name, detail._master_id_db_field_name, \
                    delta.ID, detail._master_rec_id_db_field_name, id_literal)
            else:
                sql = 'DELETE FROM "%s" WHERE "%s" = %s AND "%s" = %s' % \
                    (detail.table_name, detail._master_id_db_field_name, delta.ID, \
                    detail._master_rec_id_db_field_name, id_literal)
        else:
            if delta.soft_delete:
                sql = 'UPDATE "%s" SET "%s" = 1 WHERE "%s" = %s' % \
                    (detail.table_name, detail._deleted_flag_db_field_name, \
                    detail._master_rec_id_db_field_name, id_literal)
            else:
                sql = 'DELETE FROM "%s" WHERE "%s" = %s' % \
                    (detail.table_name, detail._master_rec_id_db_field_name, id_literal)
        if len(detail.details) or detail.keep_history:
            self.update_deleted_detail(delta, detail, cursor)
            if detail.keep_history:
                for d in detail:
                    params = [detail.prototype.ID, d._primary_key_field.data,
                        consts.RECORD_DELETED, None, self.get_user(delta), datetime.datetime.now()]
                    delta.execute_query(cursor, delta.task.history_sql, \
                        self.process_query_params(params, cursor), arg_params=self.arg_params)
            if len(detail.details):
                for it in detail:
                    for d in detail.details:
                        self.delete_detail_records(detail, connection, cursor, d)
        delta.execute_query(cursor, sql)

    def process_record(self, delta, connection, cursor, safe, changes, details_changes):
        if delta.master:
            if delta._master_id:
                delta._master_id_field.data = delta.master.ID
            delta._master_rec_id_field.data = delta.master._primary_key_field.value
        if delta.record_status == consts.RECORD_INSERTED:
            if safe and not delta.can_create():
                raise Exception(consts.language('cant_create') % delta.item_caption)
            self.insert_record(delta, cursor, changes, details_changes)
        elif delta.record_status == consts.RECORD_MODIFIED:
            if safe and not delta.can_edit():
                raise Exception(consts.language('cant_edit') % delta.item_caption)
            self.update_record(delta, cursor, changes, details_changes)
        elif delta.record_status == consts.RECORD_DETAILS_MODIFIED:
            pass
        elif delta.record_status == consts.RECORD_DELETED:
            if safe and not delta.can_delete():
                raise Exception(consts.language('cant_delete') % delta.item_caption)
            self.delete_record(delta, cursor, changes, details_changes)
        else:
            raise Exception('execute_delta - invalid %s record_status %s, record: %s' % \
                (delta.item_name, delta.record_status, delta._dataset[delta.rec_no]))
        self.save_history(delta, connection, cursor)

    def process_records(self, delta, connection, cursor, safe, changes):
        for it in delta:
            details = []
            self.process_record(it, connection, cursor, safe, changes, details)
            for detail in delta.details:
                detail_changes = []
                detail_result = {'ID': str(detail.ID), 'changes': detail_changes}
                details.append(detail_result)
                if delta.record_status == consts.RECORD_DELETED:
                    self.delete_detail_records(delta, connection, cursor, detail)
                else:
                    self.process_records(detail, connection, cursor, safe, detail_changes)

    def process_changes(self, delta, connection, params=None):
        error = None
        safe = False
        if params:
            safe = params['__safe']
        changes = []
        result = {'ID': str(delta.ID), 'changes': changes}
        cursor = connection.cursor()
        self.process_records(delta, connection, cursor, safe, changes)
        return result, error

    def table_alias(self, item):
        return '"%s"' % item.table_name

    def lookup_table_alias(self, item, field):
        if field.master_field:
            return '%s_%d' % (field.lookup_item.table_name, field.master_field.ID)
        else:
            return '%s_%d' % (field.lookup_item.table_name, field.ID)

    def lookup_table_alias1(self, item, field):
        return self.lookup_table_alias(item, field) + '_' + field.lookup_db_field

    def lookup_table_alias2(self, item, field):
        return self.lookup_table_alias1(item, field) + '_' + field.lookup_db_field1

    def field_alias(self, item, field):
        return '%s_%s' % (field.db_field_name, self.identifier_case('LOOKUP'))

    def lookup_field_sql(self, item, field):
        if field.lookup_item:
            if field.lookup_field2:
                field_sql = '%s."%s"' % (self.lookup_table_alias2(item, field), field.lookup_db_field2)
            elif field.lookup_field1:
                field_sql = '%s."%s"' % (self.lookup_table_alias1(item, field), field.lookup_db_field1)
            else:
                if field.data_type == consts.KEYS:
                    field_sql = 'NULL'
                else:
                    field_sql = '%s."%s"' % (self.lookup_table_alias(item, field), field.lookup_db_field)
            return field_sql

    def calculated_sql(self, item, field):
        result = 'SELECT %s("%s") FROM "%s" WHERE %s.%s=%s' % \
            (field._calc_op, field._calc_field.db_field_name, field._calc_item.table_name,
            self.table_alias(item), field._calc_item._primary_key_db_field_name, field._calc_on_field.db_field_name)
        if field._calc_item._deleted_flag:
            result = '%s AND "%s"=0' % (result, field._calc_item._deleted_flag_db_field_name)
        result = '(%s) %s %s' % (result, self.FIELD_AS, self.identifier_case(field.field_name))
        return result

    def fields_clause(self, item, query, fields):
        summary = query.get('__summary')
        funcs = query.get('__funcs')
        if funcs:
            functions = {}
            for key, value in iteritems(funcs):
                functions[key.upper()] = value
        repls = query.get('__replace')
        if repls:
            replace = {}
            for key, value in iteritems(repls):
                replace[key.upper()] = value
        sql = []
        for i, field in enumerate(fields):
            if i == 0 and summary:
                sql.append(self.identifier_case('count(*)'))
            elif field.master_field:
                pass
            elif field.calculated:
                pass
                # ~ if query['__expanded']:
                    # ~ sql.append(self.calculated_sql(item, field))
            else:
                if repls and replace.get(field.field_name.upper()):
                    field_sql = ('%s %s "%s"') % (replace[field.field_name.upper()], self.FIELD_AS, field.db_field_name)
                else:
                    field_sql = '%s."%s"' % (self.table_alias(item), field.db_field_name)
                    func = None
                    if funcs:
                        func = functions.get(field.field_name.upper())
                        if func:
                            field_sql = '%s(%s) %s "%s"' % (func.upper(), field_sql, self.FIELD_AS, field.db_field_name)
                sql.append(field_sql)
        for i, field in enumerate(fields):
            if field.calculated:
                if query['__expanded']:
                    sql.append(self.calculated_sql(item, field))
        if query['__expanded']:
            for i, field in enumerate(fields):
                if i == 0 and summary:
                    continue
                field_sql = self.lookup_field_sql(item, field)
                field_alias = self.field_alias(item, field)
                if field_sql:
                    if funcs:
                        func = functions.get(field.field_name.upper())
                    if func:
                        field_sql = '%s(%s) %s "%s"' % (func.upper(), field_sql, self.FIELD_AS, field_alias)
                    else:
                        field_sql = '%s %s %s' % (field_sql, self.FIELD_AS, field_alias)
                    sql.append(field_sql)
        sql = ', '.join(sql)
        return sql

    def from_clause(self, item, query, fields):
        result = []
        result.append(self.FROM % (item.table_name, self.table_alias(item)))
        if query['__expanded']:
            joins = {}
            for field in fields:
                if field.lookup_item and field.data_type != consts.KEYS:
                    alias = self.lookup_table_alias(item, field)
                    cur_field = field
                    if field.master_field:
                        cur_field = field.master_field
                    if not joins.get(alias):
                        primary_key_field_name = field.lookup_item._primary_key_db_field_name
                        result.append('%s ON %s."%s" = %s."%s"' % (
                            self.LEFT_OUTER_JOIN % (field.lookup_item.table_name, self.lookup_table_alias(item, field)),
                            self.table_alias(item),
                            cur_field.db_field_name,
                            self.lookup_table_alias(item, field),
                            primary_key_field_name
                        ))
                        joins[alias] = True
                if field.lookup_item1:
                    alias = self.lookup_table_alias1(item, field)
                    if not joins.get(alias):
                        primary_key_field_name = field.lookup_item1._primary_key_db_field_name
                        result.append('%s ON %s."%s" = %s."%s"' % (
                            self.LEFT_OUTER_JOIN % (field.lookup_item1.table_name, self.lookup_table_alias1(item, field)),
                            self.lookup_table_alias(item, field),
                            field.lookup_db_field,
                            self.lookup_table_alias1(item, field),
                            primary_key_field_name
                        ))
                        joins[alias] = True
                if field.lookup_item2:
                    alias = self.lookup_table_alias2(item, field)
                    if not joins.get(alias):
                        primary_key_field_name = field.lookup_item2._primary_key_db_field_name
                        result.append('%s ON %s."%s" = %s."%s"' % (
                            self.LEFT_OUTER_JOIN % (field.lookup_item2.table_name, self.lookup_table_alias2(item, field)),
                            self.lookup_table_alias1(item, field),
                            field.lookup_db_field1,
                            self.lookup_table_alias2(item, field),
                            primary_key_field_name
                        ))
                        joins[alias] = True
        return ' '.join(result)

    def get_filter_sign(self, item, filter_type, value):
        result = consts.FILTER_SIGN[filter_type]
        if filter_type == consts.FILTER_ISNULL:
            if value:
                result = 'IS NULL'
            else:
                result = 'IS NOT NULL'
        return result

    def convert_field_value(self, item, field, value, filter_type):
        data_type = field.data_type
        if filter_type and filter_type in [consts.FILTER_CONTAINS, consts.FILTER_STARTWITH, consts.FILTER_ENDWITH]:
            if data_type == consts.FLOAT:
                value = field.str_to_float(value)
            elif data_type == consts.CURRENCY:
                value = field.str_to_cur(value)
            if type(value) == float:
                if int(value) == value:
                    value = str(int(value)) + '.'
                else:
                    value = str(value)
            return value
        else:
            if data_type == consts.DATE:
                if type(value) in string_types:
                    result = value
                else:
                    result = value.strftime('%Y-%m-%d')
                return self.cast_date(result)
            elif data_type == consts.DATETIME:
                if type(value) in string_types:
                    result = value
                else:
                    result = value.strftime('%Y-%m-%d %H:%M:%S')
                result = self.cast_datetime(result)
                return result
            elif data_type == consts.INTEGER:
                if type(value) in integer_types or type(value) in string_types and value.isdigit():
                    return str(value)
                else:
                    return "'" + value + "'"
            elif data_type == consts.BOOLEAN:
                if value:
                    return '1'
                else:
                    return '0'
            elif data_type == consts.TEXT:
                return "'" + to_unicode(value) + "'"
            elif data_type in (consts.FLOAT, consts.CURRENCY):
                return str(float(value))
            else:
                return value

    def escape_search(self, value, esc_char):
        result = ''
        found = False
        for ch in value:
            if ch == "'":
                ch = ch + ch
            elif ch in ['_', '%']:
                ch = esc_char + ch
                found = True
            result += ch
        return result, found

    def get_condition(self, item, field, filter_type, value):
        esc_char = '/'
        cond_field_name = '%s."%s"' % (self.table_alias(item), field.db_field_name)
        if type(value) == str:
            value = to_unicode(value, 'utf-8')
        filter_sign = self.get_filter_sign(item, filter_type, value)
        cond_string = '%s %s %s'
        if filter_type in (consts.FILTER_IN, consts.FILTER_NOT_IN):
            values = [self.convert_field_value(item, field, v, filter_type) for v in value if v is not None]
            value = '(%s)' % ', '.join(values)
        elif filter_type == consts.FILTER_RANGE:
            value = self.convert_field_value(item, field, value[0], filter_type) + \
                ' AND ' + self.convert_field_value(item, field, value[1], filter_type)
        elif filter_type == consts.FILTER_ISNULL:
            value = ''
        else:
            value = self.convert_field_value(item, field, value, filter_type)
            if filter_type in [consts.FILTER_CONTAINS, consts.FILTER_STARTWITH, consts.FILTER_ENDWITH]:
                value, esc_found = self.escape_search(value, esc_char)
                if field.lookup_item:
                    if field.lookup_item1:
                        cond_field_name = '%s."%s"' % (self.lookup_table_alias1(item, field), field.lookup_db_field1)
                    else:
                        if field.data_type == consts.KEYS:
                            cond_field_name = '%s."%s"' % (self.table_alias(item), field.db_field_name)
                        else:
                            cond_field_name = '%s."%s"' % (self.lookup_table_alias(item, field), field.lookup_db_field)

                if filter_type == consts.FILTER_CONTAINS:
                    value = '%' + value + '%'
                elif filter_type == consts.FILTER_STARTWITH:
                    value = value + '%'
                elif filter_type == consts.FILTER_ENDWITH:
                    value = '%' + value
                cond_field_name, value = self.convert_like(cond_field_name, value, field.data_type)
                if esc_found:
                    value = "'" + value + "' ESCAPE '" + esc_char + "'"
                else:
                    value = "'" + value + "'"
        sql = cond_string % (cond_field_name, filter_sign, value)
        if field.data_type == consts.BOOLEAN and not field.not_null and value == '0':
            if filter_sign == '=':
                sql = '(' + sql + ' OR %s IS NULL)' % cond_field_name
        if filter_sign == '<>' and not field.not_null:
            sql = '(' + sql + ' AND %s IS NOT NULL)' % cond_field_name
        return sql

    def add_master_conditions(self, item, query, conditions):
        master_id = query['__master_id']
        master_rec_id = query['__master_rec_id']
        if master_id and master_rec_id:
            if item._master_id:
                conditions.append('%s."%s"=%s' % \
                    (self.table_alias(item), item._master_id_db_field_name, str(master_id)))
                conditions.append('%s."%s"=%s' % \
                    (self.table_alias(item), item._master_rec_id_db_field_name, str(master_rec_id)))

    def where_clause(self, item, query):
        conditions = []
        if item.master:
            self.add_master_conditions(item,query, conditions)
        filters = query['__filters']
        deleted_in_filters = False
        if filters:
            for field_name, filter_type, value in filters:
                if not value is None:
                    field = item._field_by_name(field_name)
                    if field_name == item._deleted_flag:
                        deleted_in_filters = True
                    if filter_type == consts.FILTER_CONTAINS_ALL:
                        values = value.split()
                        for val in values:
                            conditions.append(self.get_condition(item, field, consts.FILTER_CONTAINS, val))
                    elif filter_type in [consts.FILTER_IN, consts.FILTER_NOT_IN] and \
                        type(value) in [tuple, list] and len(value) == 0:
                        conditions.append('%s."%s" IN (NULL)' % (self.table_alias(item), item._primary_key_db_field_name))
                    else:
                        conditions.append(self.get_condition(item, field, filter_type, value))
        if not deleted_in_filters and item._deleted_flag:
            conditions.append('%s."%s"=0' % (self.table_alias(item), item._deleted_flag_db_field_name))
        result = ' AND '.join(conditions)
        if result:
            result = ' WHERE ' + result
        return result

    def group_clause(self, item, query, fields):
        group_fields = query.get('__group_by')
        funcs = query.get('__funcs')
        if funcs:
            functions = {}
            for key, value in iteritems(funcs):
                functions[key.upper()] = value
        result = ''
        if group_fields:
            for field_name in group_fields:
                field = item._field_by_name(field_name)
                if query['__expanded'] and field.lookup_item and field.data_type != consts.KEYS:
                    func = functions.get(field.field_name.upper())
                    if func:
                        result += '%s."%s", ' % (self.table_alias(item), field.db_field_name)
                    else:
                        result += '%s, %s."%s", ' % (self.lookup_field_sql(item, field),
                            self.table_alias(item), field.db_field_name)
                else:
                    result += '%s."%s", ' % (self.table_alias(item), field.db_field_name)
            if result:
                result = result[:-2]
                result = ' GROUP BY ' + result
            return result
        else:
            return ''

    def order_clause(self, item, query):
        limit = query.get('__limit')
        if limit and not query.get('__order') and item._primary_key:
            query['__order'] = [[item._primary_key, False]]
        if query.get('__funcs') and not query.get('__group_by'):
            return ''
        funcs = query.get('__funcs')
        functions = {}
        if funcs:
            for key, value in iteritems(funcs):
                functions[key.upper()] = value
        order_list = query.get('__order', [])
        orders = []
        for order in order_list:
            field = item._field_by_name(order[0])
            if field:
                func = functions.get(field.field_name.upper())
                if not query['__expanded'] and field.lookup_item1:
                   orders = []
                   break
                if query['__expanded'] and field.lookup_item:
                    if field.data_type == consts.KEYS:
                        ord_str = '%s."%s"' % (self.table_alias(item), field.db_field_name)
                    else:
                        if func:
                            ord_str = self.field_alias(item, field)
                        else:
                            ord_str = self.lookup_field_sql(item, field)
                elif field.calculated:
                    ord_str = self.identifier_case(field.field_name)
                else:
                    if func:
                        if self.db_type == consts.MSSQL and limit:
                            ord_str = '%s(%s."%s")' %  (func, self.table_alias(item), field.db_field_name)
                        else:
                            ord_str = '"%s"' % field.db_field_name
                    else:
                        ord_str = '%s."%s"' % (self.table_alias(item), field.db_field_name)
                if order[1]:
                    ord_str += ' DESC'
                    if self.DESC_NULLS:
                        ord_str += ' %s' % self.DESC_NULLS
                elif self.ASC_NULLS:
                    ord_str += ' ASC %s' % self.ASC_NULLS
                orders.append(ord_str)
        if orders:
             result = ' ORDER BY %s' % ', '.join(orders)
        else:
            result = ''
        return result

    def split_query(self, query):
        MAX_IN_LIST = 1000
        filters = query['__filters']
        filter_index = -1
        max_list = 0
        if filters:
            for i, f in enumerate(filters):
                field_name, filter_type, value = f
                if filter_type in [consts.FILTER_IN, consts.FILTER_NOT_IN]:
                    length = len(value)
                    if length > MAX_IN_LIST and length > max_list:
                        max_list = length
                        filter_index = i
        if filter_index != -1:
            lists = []
            value_list = filters[filter_index][2]
            while True:
                values = value_list[0:MAX_IN_LIST]
                if values:
                    lists.append(values)
                value_list = value_list[MAX_IN_LIST:]
                if not value_list:
                    break;
            return filter_index, lists

    def get_select_queries(self, item, query):
        result = []
        filter_in_info = self.split_query(query)
        if filter_in_info:
            filter_index, lists = filter_in_info
            for lst in lists:
                query['__limit'] = None
                query['__offset'] = None
                query['__filters'][filter_index][2] = lst
                result.append(self.get_select_query(item, query))
        else:
            result.append(self.get_select_query(item, query))
        return result

    def get_select_statement(self, item, query): # depricated
        return self.get_select_query(item, query)

    def get_select_query(self, item, query):
        try:
            field_list = query['__fields']
            if len(field_list):
                fields = [item._field_by_name(field_name) for field_name in field_list]
            else:
                fields = item._fields
            fields_clause = self.fields_clause(item, query, fields)
            from_clause = self.from_clause(item, query, fields)
            where_clause = self.where_clause(item, query)
            group_clause = self.group_clause(item, query, fields)
            order_clause = self.order_clause(item, query)
            sql = self.get_select(query, fields_clause, from_clause, where_clause, group_clause, order_clause, fields)
            return sql
        except Exception as e:
            item.log.exception(error_message(e))
            raise

    def get_record_count_queries(self, item, query):
        result = []
        filter_in_info = self.split_query(query)
        if filter_in_info:
            filter_index, lists = filter_in_info
            for lst in lists:
                query['__filters'][filter_index][2] = lst
                result.append(item.get_record_count_query(query))
        else:
            result.append(item.get_record_count_query(query))
        return result

    def get_record_count_query(self, item, query):
        fields = []
        filters = query['__filters']
        if filters:
            for (field_name, filter_type, value) in filters:
                fields.append(item._field_by_name(field_name))
        sql = 'SELECT COUNT(*) FROM %s %s' % (self.from_clause(item, query, fields),
            self.where_clause(item, query))
        return sql

    def empty_table_query(self, item):
        return 'DELETE FROM %s' % item.table_name