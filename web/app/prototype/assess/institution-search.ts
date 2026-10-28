'use server';
import { chineseInstitutions } from '../../../lib/prototype-library-server';
import { searchInstitutions, paginate } from '../../../lib/prototype-library';
export async function findInstitutions(query: string, page = '1') {
  return paginate(searchInstitutions(chineseInstitutions, query.slice(0,100)),page,20);
}
